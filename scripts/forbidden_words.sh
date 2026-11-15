#!/usr/bin/env sh
# Refuse a commit that contains any word listed in .forbidden-words.local, one per line,
# matched case-insensitively. The list is never committed (*.local is gitignored), so a
# name that must stay out of the repository does not enter it through the hook itself.
# Without the file the hook passes. The repository's own address, read from pyproject.toml, is
# taken out of a file before it is searched: where the project lives is not a name it gives out.
list=".forbidden-words.local"
[ -f "$list" ] || exit 0
own=$(sed -n 's#^Repository = "https\{0,1\}://\(.*\)"$#\1#p' pyproject.toml 2>/dev/null | head -n 1)
status=0
while IFS= read -r word || [ -n "$word" ]; do
  [ -z "$word" ] && continue
  case "$word" in '#'*) continue ;; esac
  for file in "$@"; do
    if sed "s#${own:-@@no-address@@}##g" "$file" 2>/dev/null | grep -i -F -- "$word" >/dev/null 2>&1; then
      echo "$file: contains a forbidden word from $list"
      status=1
    fi
  done
done < "$list"
exit $status
