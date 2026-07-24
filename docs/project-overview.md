# Project Overview

## What is PCS

PCS (Pacemaker/Corosync Configuration System) is a tool for configuring and
managing HA (High Availability) clusters based on Pacemaker and Corosync. See
[README.md](../README.md) for technical details.

## Context

PCS operates in the HA cluster ecosystem:
- **Pacemaker** — cluster resource manager
- **Corosync** — cluster communication layer
- **PCS** — configuration and management interface (CLI + daemon)

Users interact with PCS to configure cluster nodes, resources, constraints, and
other aspects rather than editing raw XML and other configuration files.

## Evolution

The project has a long history. Requirements, understanding, and vision have
evolved over time. To maintain stability and continuity with limited resources,
we've had to accept legacy code alongside new approaches.

### Ruby to Python migration

Ruby was used early in the project. Maintaining two language ecosystems is
costly, so we're gradually migrating to Python-only.

**Current state:**
- Main codebase is Python
- Legacy Ruby daemon still runs alongside the Tornado daemon (see
  [architecture/daemon.md](architecture/daemon.md))
- Ruby code is being phased out, not expanded

**Ruby code as a knowledge source:** While Ruby code should not be used as a
template for new Python code (different idioms, different architecture), it often
contains valuable domain knowledge accumulated over years of development and user
feedback — edge case handling, retry logic, authentication details, error
conditions. When implementing Python replacements for Ruby functionality, review
the corresponding Ruby code for **what concerns it addresses**, not for how it
implements them.

### APIv2 migration

APIv2 is replacing the older synchronous API layers. See
[architecture/daemon.md](architecture/daemon.md) for details on API layers and
the APIv2 architecture.

**Why:**
- Enables async request processing
- Modern HTTP API patterns

**Current state:**
- APIv2 implementation exists and is being expanded
- Old synchronous APIs still present
- Migration ongoing, not complete

## Git Branches

- The project has multiple production branches: 'main' branch and several
  'pcs-$version' (e.g. pcs-0.10, pcs-0.11, pcs-1.0) branches.
- A branch which is supposed to be merged to a 'pcs-$version' branch is
  supposed to be prefixed with that branch name, e.g. `pcs-0.11_new-feature`. A
  branch which is supposed to be merged to the main branch is not prefixed like
  this.

## Development philosophy

See [development-principles.md](development-principles.md) for detailed
guidelines.

Key points:
- **Stability first** — breaking changes are avoided when possible
- **Compatibility matters** — we depend on Linux, Pacemaker, Corosync, Python,
  and (temporarily) Ruby
- **Pragmatic evolution** — we improve architecture while keeping the app
  functional, so not all code reflects the target vision
