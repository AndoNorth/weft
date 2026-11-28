# Dry run by default; --publish tags, pushes and creates the GitHub Release. See docs/delivery/release-process.md.
release version *flags:
    scripts/release.sh {{ version }} {{ flags }}
