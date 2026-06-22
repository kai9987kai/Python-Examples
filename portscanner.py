#!/usr/bin/env python3
"""
Script Name     : portscanner.py
Author          : Craig Richards / Improved
Description     : Threaded TCP port scanner supporting individual ports and port ranges.
"""

import argparse
import sys
from socket import socket, AF_INET, SOCK_STREAM, gethostbyname, gethostbyaddr, setdefaulttimeout
from threading import Thread, Semaphore

# Semaphore to prevent print overlap from multiple threads
screen_lock = Semaphore(value=1)


def conn_scan(tgt_host, tgt_port, verbose=False):
    """Attempts to connect to a target host and port to see if it is open."""
    try:
        conn_skt = socket(AF_INET, SOCK_STREAM)
        conn_skt.connect((tgt_host, tgt_port))
        
        # In Python 3, socket.send() requires a bytes-like object, not a str.
        # This was a major bug in the original script.
        conn_skt.send(b'\r\n')
        
        results = conn_skt.recv(100)
        
        with screen_lock:
            print(f'[+] {tgt_port}/tcp open')
            if results:
                # Print banner response if received
                try:
                    banner = results.decode('utf-8', errors='ignore').strip()
                    if banner:
                        print(f'   [Banner] {banner}')
                except Exception:
                    pass
    except Exception:
        if verbose:
            with screen_lock:
                print(f'[-] {tgt_port}/tcp closed')
    finally:
        conn_skt.close()


def port_scan(tgt_host, tgt_ports, verbose=False):
    """Resolves target host and spawns threads for each port scanning attempt."""
    try:
        tgt_ip = gethostbyname(tgt_host)
    except Exception:
        print(f"[-] Cannot resolve '{tgt_host}': Unknown host")
        return

    try:
        tgt_name = gethostbyaddr(tgt_ip)
        print(f'\n[+] Scan Results for: {tgt_name[0]} ({tgt_ip})')
    except Exception:
        print(f'\n[+] Scan Results for: {tgt_ip}')

    setdefaulttimeout(1.5)
    
    threads = []
    try:
        for tgt_port in tgt_ports:
            # Spawn daemon threads so they terminate immediately if the user exits via Ctrl+C
            t = Thread(target=conn_scan, args=(tgt_host, tgt_port, verbose), daemon=True)
            threads.append(t)
            t.start()

        # Join threads while keeping main thread active for KeyboardInterrupt signals
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.1)
                
    except KeyboardInterrupt:
        print("\n[-] Scan cancelled by user. Terminating threads...")
        sys.exit(0)


def parse_ports(ports_str):
    """Parses ports argument supporting individual ports and ranges (e.g. 80,443,8000-8010)."""
    ports = []
    for part in ports_str.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-')
                start_port = int(start)
                end_port = int(end)
                if start_port < 1 or end_port > 65535 or start_port > end_port:
                    raise ValueError
                ports.extend(range(start_port, end_port + 1))
            except ValueError:
                raise argparse.ArgumentTypeError(f"Invalid port range: '{part}'. Ports must be between 1 and 65535.")
        else:
            try:
                port = int(part)
                if port < 1 or port > 65535:
                    raise ValueError
                ports.append(port)
            except ValueError:
                raise argparse.ArgumentTypeError(f"Invalid port: '{part}'. Port must be an integer between 1 and 65535.")
                
    if not ports:
        raise argparse.ArgumentTypeError("No valid ports specified.")
    return sorted(list(set(ports)))


def main():
    parser = argparse.ArgumentParser(description="Threaded TCP Port Scanner.")
    parser.add_argument('host', type=str, help='Target host name or IP address.')
    parser.add_argument('ports', type=str, help='Comma-separated ports or ranges (e.g. 80,443,8000-8010).')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show closed ports as well (default: only show open ports).')
    
    args = parser.parse_args()

    try:
        ports_list = parse_ports(args.ports)
    except argparse.ArgumentTypeError as e:
        print(f"[-] Error: {e}")
        sys.exit(1)

    port_scan(args.host, ports_list, args.verbose)


if __name__ == '__main__':
    main()