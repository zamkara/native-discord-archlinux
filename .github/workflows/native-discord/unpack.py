#!/usr/bin/env python3
"""Extract an official archive without traversal, links, devices or outside entries."""
from pathlib import Path, PurePosixPath
import sys
import tarfile


def unpack(source, destination, folder):
    with tarfile.open(source,'r:*') as archive:
        members=archive.getmembers()
        if len(members)>20000 or sum(m.size for m in members)>2*1024**3:
            raise ValueError('Archive exceeds build limits')
        for m in members:
            path=PurePosixPath(m.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!=folder:
                raise ValueError('Unexpected archive path')
            if not (m.isfile() or m.isdir()):raise ValueError('Links and special files are not accepted')
            if m.mode & 0o7000:raise ValueError('Privileged archive permissions are not accepted')
        Path(destination).mkdir(parents=True,exist_ok=True)
        archive.extractall(destination,members=members,filter='data')


if __name__=='__main__':unpack(*sys.argv[1:])
