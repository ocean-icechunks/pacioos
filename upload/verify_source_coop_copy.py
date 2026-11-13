#!/usr/bin/env python3
"""Check files on Source Cooperative against the .md5 files uploaded next to them.

Anyone can run this, anywhere: it needs no login and only Python 3.6 or newer, with no extra
packages. It downloads each file over public HTTPS, computes its MD5 as the bytes arrive (nothing
is saved to disk), and compares the result with the checksum that `upload_to_source_coop.sh`
computed on the source machine before uploading.

    python3 verify_source_coop_copy.py pacioos/roms_hiig/netcdf/            # every file in a product
    python3 verify_source_coop_copy.py pacioos/roms_hiig/netcdf/2026/ --sample 10   # a random 10
    python3 verify_source_coop_copy.py pacioos/ --list-only          # sizes and .md5s, no downloads

One line per file is printed:
    OK       the downloaded bytes match the .md5
    BAD      they do not; upload that file again
    NO-MD5   there is no .md5 file, so the upload never finished; run the upload script again
It exits with status 1 if any file is BAD or NO-MD5.

Downloading is fast from a cloud machine (about 40 MB/s per file from AWS us-west-2), but it
uses that machine's bandwidth, not the source server's. So run it from somewhere other than the
server that holds the originals.
"""
import argparse
import hashlib
import random
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ENDPOINT = "https://data.source.coop"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
HEADERS = {"User-Agent": "pacioos-copy-check/1.0"}  # Source Cooperative refuses Python's default


def get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


def list_objects(account, prefix):
    """All (key, size) under account/prefix, using the public S3 listing (ListObjectsV2)."""
    token = None
    while True:
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        url = "%s/%s?%s" % (ENDPOINT, account, urllib.parse.urlencode(query))
        root = ET.fromstring(get(url).read())
        for c in root.findall("s3:Contents", NS):
            yield c.find("s3:Key", NS).text, int(c.find("s3:Size", NS).text)
        if root.findtext("s3:IsTruncated", namespaces=NS) != "true":
            return
        token = root.findtext("s3:NextContinuationToken", namespaces=NS)


def md5_of_url(url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            h, n = hashlib.md5(), 0
            with get(url, timeout=120) as r:
                for block in iter(lambda: r.read(8 << 20), b""):
                    h.update(block)
                    n += len(block)
            return h.hexdigest(), n
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5 * attempt)


def check(account, key, size, expected):
    url = "%s/%s/%s" % (ENDPOINT, account, urllib.parse.quote(key))
    t = time.time()
    try:
        got, n = md5_of_url(url)
    except Exception as e:
        return "BAD", "%s  (download failed: %s)" % (key, e)
    dt = max(time.time() - t, 0.001)
    detail = "%s  size=%d  md5=%s  (%.0f MB/s)" % (key, n, got, n / dt / 1e6)
    if got == expected and n == size:
        return "OK", detail
    return "BAD", "%s  expected md5=%s size=%d" % (detail, expected, size)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("prefix", help="product folder to check, e.g. pacioos/roms_hiig/netcdf/")
    p.add_argument("--account", default="ocean-icechunks", help="Source Cooperative account")
    p.add_argument("--sample", type=int, default=0, help="check only this many files, at random")
    p.add_argument("--parallel", type=int, default=4, help="files downloaded at the same time")
    p.add_argument("--list-only", action="store_true", help="report sizes and .md5s, no downloads")
    a = p.parse_args()

    objects = dict(list_objects(a.account, a.prefix))
    data = sorted(k for k in objects if not k.endswith(".md5"))
    no_md5 = [k for k in data if k + ".md5" not in objects]
    todo = [k for k in data if k + ".md5" in objects]
    total = sum(objects[k] for k in data)
    print("%d files (%.1f GB) under %s/%s; %d with a .md5"
          % (len(data), total / 1e9, a.account, a.prefix, len(todo)))

    bad = 0
    for k in no_md5:
        print("NO-MD5  %s  size=%d" % (k, objects[k]))
        bad += 1
    if a.list_only:
        return 1 if bad else 0
    if a.sample and a.sample < len(todo):
        todo = sorted(random.sample(todo, a.sample))

    def expected_md5(k):
        url = "%s/%s/%s.md5" % (ENDPOINT, a.account, urllib.parse.quote(k))
        return get(url).read().decode().split()[0]

    with ThreadPoolExecutor(a.parallel) as pool:
        jobs = [pool.submit(lambda k=k: check(a.account, k, objects[k], expected_md5(k))) for k in todo]
        for j in jobs:
            status, detail = j.result()
            print("%-7s %s" % (status, detail), flush=True)
            bad += status != "OK"
    print("%d checked, %d problems" % (len(todo), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
