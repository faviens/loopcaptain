#!/usr/bin/env sh
# Refuse a commit that contains any word listed in .forbidden-words.local, one per line,
# matched case-insensitively. The list is never committed (*.local is gitignored), so a
# name that must stay out of the repository does not enter it through the hook itself.
# Without the file the hook passes. The repository's own addresses, read from pyproject.toml, are
# taken out of a file before it is searched: its path as badges name it (owner/repo) and its
# documentation site (owner.github.io/repo). Where the project lives is not a name it gives out.
list=".forbidden-words.local"
[ -f "$list" ] || exit 0
own=$(sed -n 's#^Repository = "https\{0,1\}://[^/]*/\([^/"]*/[^/"]*\)/\{0,1\}"$#\1#p' pyproject.toml 2>/dev/null | head -n 1)
owner=${own%%/*}
repo=${own#*/}
status=0
while IFS= read -r word || [ -n "$word" ]; do
  [ -z "$word" ] && continue
  case "$word" in '#'*) continue ;; esac
  for file in "$@"; do
    if sed -e "s#${owner:-@@none@@}\.github\.io/${repo}##g" -e "s#${own:-@@none@@}##g" "$file" 2>/dev/null \
      | grep -i -F -- "$word" >/dev/null 2>&1; then
      echo "$file: contains a forbidden word from $list"
      status=1
    fi
  done
done < "$list"
exit $status
