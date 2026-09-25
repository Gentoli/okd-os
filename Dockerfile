# oc adm release info --image-for stream-coreos
ARG BASE_IMAGE=quay.io/okd/scos-content@sha256:ea9c3617059d50829367a3b6fad651bfee2513986828cf1a181bfea5f0818643
FROM ${BASE_IMAGE}

ARG VERSION="6.12.0-250.el10"

#Install hotfix rpm
RUN set -eux; \
    curl -fsSLo /tmp/kernel-$VERSION.x86_64.rpm https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-$VERSION.x86_64.rpm; \
    curl -fsSLo /tmp/kernel-core-$VERSION.x86_64.rpm https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-core-$VERSION.x86_64.rpm; \
    curl -fsSLo /tmp/kernel-modules-$VERSION.x86_64.rpm https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-modules-$VERSION.x86_64.rpm; \
    curl -fsSLo /tmp/kernel-modules-core-$VERSION.x86_64.rpm https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-modules-core-$VERSION.x86_64.rpm; \
    curl -fsSLo /tmp/kernel-modules-extra-$VERSION.x86_64.rpm https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-modules-extra-$VERSION.x86_64.rpm; \
    rpm-ostree override replace \
        /tmp/kernel-$VERSION.x86_64.rpm \
        /tmp/kernel-core-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-core-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-extra-$VERSION.x86_64.rpm; \
    rm -f \
        /tmp/kernel-$VERSION.x86_64.rpm \
        /tmp/kernel-core-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-core-$VERSION.x86_64.rpm \
        /tmp/kernel-modules-extra-$VERSION.x86_64.rpm; \
    rpm-ostree cleanup -m; \
    ostree container commit
