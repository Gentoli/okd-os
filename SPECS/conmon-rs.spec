# The following tag is to get correct syntax highlighting for this file in vim text editor
# vim: syntax=spec

%global with_debug 0

%if 0%{?with_debug}
%global _find_debuginfo_dwz_opts %{nil}
%global _dwz_low_mem_die_limit 0
%else
%global debug_package %{nil}
%endif

%global bin_name conmonrs

Name: conmon-rs
Version: 0.6.6
Release: 1%{?dist}
Summary: Container monitor in Rust
License: ASL 2.0 and BSD and ISC and MIT
URL: https://github.com/containers/conmon-rs
Source0: https://github.com/containers/conmon-rs/releases/download/v%{version}/%{bin_name}-v%{version}.tar.gz
BuildRequires: capnproto
BuildRequires: cargo
BuildRequires: git-core
BuildRequires: make
BuildRequires: protobuf-compiler
%if "0%{?rhel}"
BuildRequires:  rust-toolset
%else
BuildRequires:  rust-packaging
%endif
Provides: %{bin_name}
ExclusiveArch: %{rust_arches}

%description
%{summary}.

%prep
%autosetup -n %{bin_name}-v%{version}

%build
%{__make} release

%install
%{__make} DESTDIR=%{buildroot} PREFIX=%{_prefix} install

%files
%license LICENSE
%{_bindir}/%{bin_name}

%changelog
* Fri Oct 25 2024 Dennis Gilmore <dennis@ausil.us> - 0.6.6-1
- update to 0.6.6

* Thu May 25 2023 Christian Glombek <cglombek@redhat.com> - 0.5.1-1
- Initial Release
