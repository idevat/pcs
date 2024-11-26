#!/bin/sh

makefile="$1"
inside_extra_dist=0
file_names=""

extra_dist_pattern='^\s*EXTRA_DIST\s*='

is_start_line() {
  [ $inside_extra_dist -eq 0 ] && echo "$1" | grep -q "$extra_dist_pattern"
}

is_last_line()  {
  [ $inside_extra_dist -eq 1 ] && [ "$(printf "%s" "$1" | tail -c 1)" != "\\" ]
}

remove_slash() {
  printf "%s" "$1" | sed 's|\(\\\)\?\s*$||'
}

extract_start_line() {
  remove_slash "$1" | sed "s|$extra_dist_pattern||"
}

while IFS= read -r line; do
  if is_start_line "$line"; then
    inside_extra_dist=1
    file_names="$(extract_start_line "$line")"

  elif [ $inside_extra_dist -eq 1 ]; then
    file_names="$file_names $(remove_slash "$line")"
  fi

  if is_last_line "$line"; then
    break
  fi
done < "$makefile"

echo "$file_names" |
  sed "s|^\s*||" |
  tr --squeeze-repeats '[:space:]' '\n' |
  sed "s|^|${makefile%Makefile.am}|"
