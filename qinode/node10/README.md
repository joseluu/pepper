# Node.js 10 for Pepper Robot

Pre10.24-built Node.js .1 (LTS) for Pepper robot (i686, glibc 2.23 compatible).

## Why Node.js 10?

- Required for vigiclient-pepper (Socket.IO 2.3)
- Last LTS version compatible with glibc 2.23 (NAOqiOS)
- Built on Ubuntu 16.04 (i386) for ABI compatibility

## Installation

```bash
# On the robot
cd /data
tar xzf node10_pepper.tar.gz

# Add to PATH (add to ~/.bashrc for persistence)
export PATH=/data/node10/bin:$PATH

# Verify
node --version
npm --version
```

## Usage with vigiclient

```bash
cd /data/vigiclient
/data/node10/bin/node clientrobotpi.js
```

## Specifications

| Property | Value |
|----------|-------|
| Version | 10.24.1 |
| Architecture | i686 (32-bit) |
| OS | Linux |
| libc | glibc 2.23 |
| npm included | No (use --without-npm build) |

## Building from source

```dockerfile
FROM i386/ubuntu:16.04
RUN apt-get update && apt-get install -y build-essential python2.7 wget
RUN ln -sf /usr/bin/python2.7 /usr/bin/python
RUN wget https://nodejs.org/dist/v10.24.1/node-v10.24.1.tar.gz && \
    tar xzf node-v10.24.1.tar.gz && \
    cd node-v10.24.1 && \
    ./configure --prefix=/opt/node10 --without-snapshot --without-npm && \
    make -j$(nproc) && make install
```
