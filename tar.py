from __future__ import annotations

import gzip
import os
import secrets
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO


# Optional: keeps compatibility with your existing project utility.
try:
    from library.utils.file import get_filetype
except ImportError:
    get_filetype = None


class ArchiveSecurityError(Exception):
    """Raised when an archive contains unsafe entries."""


class ArchiveLimitError(Exception):
    """Raised when archive extraction exceeds configured limits."""


def _detect_format(src_file: Path) -> str:
    """
    Detect archive type using the existing project helper when available,
    then fall back to the file extension.
    """
    filename = src_file.name.lower()

    # Handle compressed TAR archives before generic .gz detection.
    if filename.endswith((
        ".tar.gz", ".tgz",
        ".tar.bz2", ".tbz", ".tbz2",
        ".tar.xz", ".txz"
    )):
        return "tar"

    if get_filetype is not None:
        try:
            result = get_filetype(str(src_file))
            if result and result[0]:
                detected = str(result[1]).lower().lstrip(".")

                aliases = {
                    "tgz": "tar",
                    "tar.gz": "tar",
                    "gzip": "gz",
                }

                return aliases.get(detected, detected)
        except Exception:
            pass

    extension_map = {
        ".tar": "tar",
        ".zip": "zip",
        ".rar": "rar",
        ".gz": "gz",
    }

    return extension_map.get(src_file.suffix.lower(), "")


def _safe_target_path(destination_root: Path, member_name: str) -> Path:
    """
    Stops entries such as:
        ../../outside.txt
        /etc/passwd
        C:\\Windows\\System32\\...
    """
    if not member_name or "\x00" in member_name:
        raise ArchiveSecurityError("压缩包内包含无效文件名")

    normalized_name = member_name.replace("\\", "/")
    posix_path = PurePosixPath(normalized_name)
    windows_path = PureWindowsPath(member_name)

    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ArchiveSecurityError(f"压缩包包含绝对路径：{member_name}")

    if not posix_path.parts or any(part in ("", ".", "..") for part in posix_path.parts):
        raise ArchiveSecurityError(f"压缩包包含不安全路径：{member_name}")

    target = (destination_root.joinpath(*posix_path.parts)).resolve()

    try:
        target.relative_to(destination_root)
    except ValueError as exc:
        raise ArchiveSecurityError(
            f"压缩包文件试图写入目标目录外：{member_name}"
        ) from exc

    return target


def _validate_limits(entries, max_members: int, max_total_bytes: int, size_getter):
    entries = list(entries)

    if len(entries) > max_members:
        raise ArchiveLimitError(
            f"压缩包文件数量过多：{len(entries)}，最大允许 {max_members}"
        )

    total_size = 0

    for entry in entries:
        size = max(0, int(size_getter(entry) or 0))
        total_size += size

        if total_size > max_total_bytes:
            raise ArchiveLimitError(
                f"解压大小超过限制：最大允许 {max_total_bytes / 1024 / 1024:.0f} MB"
            )

    return entries


def _write_stream(
    source: BinaryIO,
    target: Path,
    *,
    overwrite: bool,
    extracted_bytes: int,
    max_total_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    """Write a stream safely using a temporary file."""

    if target.exists() and not overwrite:
        raise FileExistsError(f"目标文件已存在：{target}")

    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"目标路径是目录，不能写入文件：{target}")

    target.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = target.with_name(
        f".{target.name}.{secrets.token_hex(8)}.part"
    )

    try:
        with temporary_file.open("xb") as output:
            while True:
                chunk = source.read(chunk_size)

                if not chunk:
                    break

                extracted_bytes += len(chunk)

                if extracted_bytes > max_total_bytes:
                    raise ArchiveLimitError("实际解压大小超过安全限制")

                output.write(chunk)

        os.replace(temporary_file, target)
        return extracted_bytes

    except Exception:
        temporary_file.unlink(missing_ok=True)
        raise


def _extract_tar(
    src_file: Path,
    destination: Path,
    *,
    overwrite: bool,
    max_members: int,
    max_total_bytes: int,
) -> None:
    extracted_bytes = 0

    with tarfile.open(src_file, "r:*") as archive:
        members = _validate_limits(
            archive.getmembers(),
            max_members,
            max_total_bytes,
            lambda member: member.size,
        )

        for member in members:
            target = _safe_target_path(destination, member.name)

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            # Reject symlinks, hardlinks, device files, FIFOs, etc.
            if not member.isreg():
                raise ArchiveSecurityError(
                    f"TAR 包包含不允许的文件类型：{member.name}"
                )

            source = archive.extractfile(member)

            if source is None:
                raise OSError(f"无法读取 TAR 文件内容：{member.name}")

            with source:
                extracted_bytes = _write_stream(
                    source,
                    target,
                    overwrite=overwrite,
                    extracted_bytes=extracted_bytes,
                    max_total_bytes=max_total_bytes,
                )


def _extract_zip(
    src_file: Path,
    destination: Path,
    *,
    overwrite: bool,
    max_members: int,
    max_total_bytes: int,
) -> None:
    extracted_bytes = 0

    with zipfile.ZipFile(src_file, "r") as archive:
        entries = _validate_limits(
            archive.infolist(),
            max_members,
            max_total_bytes,
            lambda info: info.file_size,
        )

        for info in entries:
            target = _safe_target_path(destination, info.filename)

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            # Prevent symbolic links stored in ZIP files.
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ArchiveSecurityError(
                    f"ZIP 包包含不允许的符号链接：{info.filename}"
                )

            with archive.open(info, "r") as source:
                extracted_bytes = _write_stream(
                    source,
                    target,
                    overwrite=overwrite,
                    extracted_bytes=extracted_bytes,
                    max_total_bytes=max_total_bytes,
                )


def _extract_rar(
    src_file: Path,
    destination: Path,
    *,
    overwrite: bool,
    max_members: int,
    max_total_bytes: int,
) -> None:
    try:
        import rarfile
    except ImportError as exc:
        raise RuntimeError(
            "RAR 支持需要安装 rarfile：pip install rarfile"
        ) from exc

    extracted_bytes = 0

    with rarfile.RarFile(src_file, "r") as archive:
        entries = _validate_limits(
            archive.infolist(),
            max_members,
            max_total_bytes,
            lambda info: getattr(info, "file_size", 0),
        )

        for info in entries:
            target = _safe_target_path(destination, info.filename)

            if info.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            with archive.open(info) as source:
                extracted_bytes = _write_stream(
                    source,
                    target,
                    overwrite=overwrite,
                    extracted_bytes=extracted_bytes,
                    max_total_bytes=max_total_bytes,
                )


def _extract_gzip(
    src_file: Path,
    destination: Path,
    *,
    overwrite: bool,
    max_total_bytes: int,
) -> str:
    filename = src_file.name

    if filename.lower().endswith(".gzip"):
        output_name = filename[:-5]
    elif filename.lower().endswith(".gz"):
        output_name = filename[:-3]
    else:
        output_name = f"{filename}.uncompressed"

    if not output_name:
        output_name = "decompressed_file"

    output_file = destination / output_name

    with gzip.open(src_file, "rb") as source:
        _write_stream(
            source,
            output_file,
            overwrite=overwrite,
            extracted_bytes=0,
            max_total_bytes=max_total_bytes,
        )

    detected_output_type = _detect_format(output_file) or "未知"
    return f"解压完成：{output_file.name}，文件格式：{detected_output_type}"


def uncompress(
    src_file: str | Path,
    dest_dir: str | Path,
    *,
    overwrite: bool = False,
    max_members: int = 10_000,
    max_total_bytes: int = 2 * 1024 * 1024 * 1024,
) -> tuple[bool, str, str]:
    """
    Safely extract TAR, TGZ/TAR.GZ, ZIP, RAR and GZ archives.

    Returns:
        (success, message, file_format)
    """
    source = Path(src_file).expanduser()

    if not source.exists() or not source.is_file():
        return False, "源文件不存在或不是普通文件", ""

    file_format = _detect_format(source)

    if file_format not in {"tar", "zip", "rar", "gz"}:
        return False, "文件格式不支持或者不是压缩文件", file_format

    try:
        destination = Path(dest_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"创建解压目录失败：{exc}", file_format

    try:
        if file_format == "tar":
            _extract_tar(
                source,
                destination,
                overwrite=overwrite,
                max_members=max_members,
                max_total_bytes=max_total_bytes,
            )
            message = f"解压完成：{destination}"

        elif file_format == "zip":
            _extract_zip(
                source,
                destination,
                overwrite=overwrite,
                max_members=max_members,
                max_total_bytes=max_total_bytes,
            )
            message = f"解压完成：{destination}"

        elif file_format == "rar":
            _extract_rar(
                source,
                destination,
                overwrite=overwrite,
                max_members=max_members,
                max_total_bytes=max_total_bytes,
            )
            message = f"解压完成：{destination}"

        else:  # gz
            message = _extract_gzip(
                source,
                destination,
                overwrite=overwrite,
                max_total_bytes=max_total_bytes,
            )

        return True, message, file_format

    except Exception as exc:
        return False, f"解压失败：{exc}", file_format
