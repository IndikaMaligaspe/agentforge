# This file prevents pytest from descending into snapshot golden-tree
# directories during test collection.  The golden trees contain generated
# Python files that are not test modules.
collect_ignore_glob = ["**/*"]
