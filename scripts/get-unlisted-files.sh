#!/bin/sh

candidate_files="$1"

makefile_list="\
./Makefile.am
./pcs/Makefile.am
./pcs_test/Makefile.am
./pcsd/Makefile.am
./data/Makefile.am"

get_mentioned_files() {
  for makefile in $1; do
    "$(dirname "$0")"/extract-extra-dist.sh "$makefile"
  done
}

for file in $candidate_files; do
  if ! get_mentioned_files "$makefile_list" | grep -q "$file" 2> /dev/null; then
    echo "$file"
  fi
done
