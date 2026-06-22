#!/usr/bin/python3
"""
Description : Converts a basic Markdown file into a styled HTML document using regex.
Author      : Antigravity
"""
import sys
import re
from pathlib import Path


def convert_markdown_to_html(markdown_text):
    """Converts basic Markdown syntax into HTML markup using regular expressions."""
    # Convert headings
    markdown_text = re.sub(r'^######\s+(.*?)$', r'<h6>\1</h6>', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^#####\s+(.*?)$', r'<h5>\1</h5>', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^####\s+(.*?)$', r'<h4>\1</h4>', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^###\s+(.*?)$', r'<h3>\1</h3>', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^##\s+(.*?)$', r'<h2>\1</h2>', markdown_text, flags=re.MULTILINE)
    markdown_text = re.sub(r'^#\s+(.*?)$', r'<h1>\1</h1>', markdown_text, flags=re.MULTILINE)

    # Convert Images: ![Alt Text](url)
    markdown_text = re.sub(r'!\[(.*?)\]\((.*?)\)', r'<img src="\2" alt="\1" />', markdown_text)

    # Convert Links: [Link Text](url)
    markdown_text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', markdown_text)

    # Convert Bold: **text** or __text__ (using lookarounds to prevent matching inside words or URLs)
    markdown_text = re.sub(r'(?<!\w)\*\*(?=\w)(.*?)(?<=\w)\*\*(?!\w)', r'<strong>\1</strong>', markdown_text)
    markdown_text = re.sub(r'(?<!\w)__(?=\w)(.*?)(?<=\w)__(?!\w)', r'<strong>\1</strong>', markdown_text)

    # Convert Italic: *text* or _text_ (using lookarounds to prevent matching inside words or URLs)
    markdown_text = re.sub(r'(?<!\w)\*(?=\w)(.*?)(?<=\w)\*(?!\w)', r'<em>\1</em>', markdown_text)
    markdown_text = re.sub(r'(?<!\w)_(?=\w)(.*?)(?<=\w)_(?!\w)', r'<em>\1</em>', markdown_text)

    # Convert Inline Code: `code`
    markdown_text = re.sub(r'`(.*?)`', r'<code>\1</code>', markdown_text)

    # Process lists and paragraphs line-by-line
    lines = markdown_text.split('\n')
    in_list = False
    html_lines = []

    for line in lines:
        line_stripped = line.strip()

        # Handle unordered list items
        if line_stripped.startswith('* ') or line_stripped.startswith('- '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            content = line_stripped[2:]
            html_lines.append(f'  <li>{content}</li>')
        else:
            if in_list:
                html_lines.append('</ul>')
                in_list = False

            # Handle headers and already converted tags
            if (line_stripped.startswith('<h') or 
                line_stripped.startswith('<img') or 
                line_stripped == ''):
                html_lines.append(line)
            else:
                # Standard paragraph
                html_lines.append(f'<p>{line_stripped}</p>')

    # Ensure list is closed if it ended at the last line
    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


def get_styled_html(body_html, title="Converted Markdown"):
    """Wraps body HTML in a modern, responsive, and visually appealing template."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #e2e8f0;
            --text-muted: #94a3b8;
            --primary-color: #6366f1;
            --primary-hover: #4f46e5;
            --border-color: #334155;
            --code-bg: #0f172a;
        }}

        body {{
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            margin: 0;
            padding: 2rem 1rem;
            display: flex;
            justify-content: center;
        }}

        .container {{
            max-width: 800px;
            width: 100%;
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2.5rem;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
        }}

        h1, h2, h3, h4, h5, h6 {{
            color: #ffffff;
            margin-top: 1.5rem;
            margin-bottom: 1rem;
            font-weight: 700;
        }}

        h1 {{
            font-size: 2.25rem;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 0.5rem;
            margin-top: 0;
        }}

        h2 {{
            font-size: 1.75rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.3rem;
        }}

        h3 {{ font-size: 1.5rem; }}

        p {{
            margin-bottom: 1.25rem;
            color: var(--text-color);
        }}

        a {{
            color: var(--primary-color);
            text-decoration: none;
            transition: color 0.2s ease-in-out;
            font-weight: 500;
        }}

        a:hover {{
            color: var(--primary-hover);
            text-decoration: underline;
        }}

        ul {{
            margin-bottom: 1.25rem;
            padding-left: 1.5rem;
        }}

        li {{
            margin-bottom: 0.5rem;
        }}

        code {{
            font-family: 'Fira Code', Consolas, Monaco, monospace;
            background-color: var(--code-bg);
            padding: 0.2rem 0.4rem;
            border-radius: 6px;
            font-size: 0.9em;
            border: 1px solid var(--border-color);
            color: #f43f5e;
        }}

        img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            margin: 1.5rem 0;
            border: 1px solid var(--border-color);
        }}

        hr {{
            border: 0;
            border-top: 1px solid var(--border-color);
            margin: 2rem 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        {body_html}
    </div>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python markdown_to_html.py <input_file.md> [output_file.html]")
        print("\nOr run interactively:")
        input_file = input("Enter path to input Markdown (.md) file: ").strip()
        if not input_file:
            print("No file specified. Exiting.")
            sys.exit(1)
        output_file = input("Enter path for output HTML file [default: output.html]: ").strip()
        if not output_file:
            output_file = "output.html"
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else str(Path(input_file).with_suffix('.html'))

    input_path = Path(input_file)
    if not input_path.is_file():
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)

    try:
        markdown_text = input_path.read_text(encoding='utf-8')
        body_html = convert_markdown_to_html(markdown_text)
        styled_html = get_styled_html(body_html, title=input_path.stem.replace('_', ' ').title())
        
        output_path = Path(output_file)
        output_path.write_text(styled_html, encoding='utf-8')
        print(f"Success! Converted '{input_file}' to styled HTML at '{output_path.resolve()}'")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
