#!/bin/sh

git_added="$(
  git diff --cached --name-only --diff-filter=A
)"

if [ -z "$git_added" ]; then
  exit 0
fi

echo "New files detected, checking if listed in EXTRA_DIST..."

unlisted_files="$(./scripts/get-unlisted-files.sh "$git_added")"

if [ -z "$unlisted_files" ]; then
  exit 0
fi

echo "Warning: The following files are not listed in any Makefile.am:"
echo "$unlisted_files"

printf "Do you want to continue with commit? (c)Continue (a)Abort: " > /dev/tty
IFS= read -r resolution < /dev/tty

case "$resolution" in
  c | C) exit 0 ;;
  a | A)
    echo "Commit aborted."
    exit 1
    ;;
esac

echo "Unknown resolution '$resolution', aborting commit..."
exit 1
