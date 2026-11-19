#!/usr/bin/env python3
"""Exchange a local service-account API key for temporary S3 credentials.

Stdout contains secrets in AWS credential-process JSON format. The SSH wrapper
captures it in memory; do not run this helper directly in a terminal or log it.
Requires boto3. The long-lived API key is sent only to Source Cooperative STS.
"""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import zlib


def read_key(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("API key must be a regular file owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("API key file must not be accessible by group or others (use chmod 600)")
    key = path.read_text().rstrip("\r\n")
    if not re.fullmatch(r"sck_[0-9A-Za-z]{36}", key):
        raise ValueError("API key format is invalid")
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    number = zlib.crc32(key[4:34].encode())
    checksum = ""
    while number:
        number, digit = divmod(number, 62)
        checksum = alphabet[digit] + checksum
    if key[34:] != checksum.zfill(6):
        raise ValueError("API key checksum is invalid")
    return key


def exchange(key, role_arn):
    import boto3
    from botocore.config import Config

    sts = boto3.client(
        "sts", endpoint_url="https://data.source.coop/.sts",
        region_name="us-west-2", aws_access_key_id="", aws_secret_access_key="",
        config=Config(connect_timeout=15, read_timeout=30, retries={"max_attempts": 2}),
    )
    result = sts.assume_role_with_web_identity(
        RoleArn=role_arn, RoleSessionName="pacioos-upload",
        WebIdentityToken=key, DurationSeconds=3600,
    )["Credentials"]
    return {
        "Version": 1,
        "AccessKeyId": result["AccessKeyId"],
        "SecretAccessKey": result["SecretAccessKey"],
        "SessionToken": result["SessionToken"],
        "Expiration": result["Expiration"].isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--role-arn", required=True)
    args = parser.parse_args()
    try:
        credentials = exchange(read_key(args.key_file), args.role_arn)
    except (ValueError, OSError) as exc:
        # Never print file contents or arbitrary SDK exception messages.
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"API-key credential setup failed: {detail}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"API-key exchange failed ({type(exc).__name__}); check access, connectivity, and boto3 installation.", file=sys.stderr)
        return 3
    print(json.dumps(credentials))
    return 0


if __name__ == "__main__":
    sys.exit(main())
