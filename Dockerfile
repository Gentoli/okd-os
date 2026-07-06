# oc adm release info --image-for stream-coreos
FROM quay.io/okd/scos-content@sha256:ea9c3617059d50829367a3b6fad651bfee2513986828cf1a181bfea5f0818643

ARG VERSION="6.12.0-243.el10"

#Install hotfix rpm
RUN rpm-ostree override replace http://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/Packages/kernel-{,core-,modules-,modules-core-,modules-extra-}$VERSION.x86_64.rpm && \
    rpm-ostree cleanup -m && \
    ostree container commit
