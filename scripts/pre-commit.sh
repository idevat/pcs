#!/bin/sh

new_files=$(git diff --cached --name-only --diff-filter=A)
missing=""

for file in $new_files; do
	if ! grep -q "$file" "$(find . -name "Makefile.am")" 2>/dev/null; then
		missing="$missing\n$file"
	fi
done

if [ -z "$missing" ]; then
	exit 0
fi

echo "Warning: The following files are not listed in any Makefile.am:"
echo "$missing"

printf "Do you want to continue with commit? (c)Continue/(a)Abort:" >/dev/tty
IFS= read -r resolution </dev/tty

case "$resolution" in
c | C) exit 0 ;;
a | A)
	echo "Commit aborted."
	exit 1
	;;
*)
	echo "Unknown resolution '$resolution', aborting..."
	exit 1
	;;
esac
