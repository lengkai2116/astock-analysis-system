#!/bin/bash
# CodeGraph CLI helper - use when codegraph_* MCP tools are unavailable
# Usage: ./cg.sh query <keyword>
#        ./cg.sh context <task description>
#        ./cg.sh status
#        ./cg.sh search <symbol>
#        ./cg.sh callers <symbol>
#        ./cg.sh callees <symbol>
#        ./cg.sh files [path]
#        ./cg.sh explore <symbols...>
#        ./cg.sh trace <from> <to>

PROJECT="/Users/kalence/Desktop/01-A股股票分析系统"

case "$1" in
  query)
    shift
    codegraph query --path "$PROJECT" "$@"
    ;;
  context)
    shift
    codegraph context --path "$PROJECT" "$@"
    ;;
  status)
    cd "$PROJECT" && codegraph status
    ;;
  search)
    shift
    codegraph query --path "$PROJECT" "$@"
    ;;
  callers)
    shift
    codegraph callers --path "$PROJECT" "$@"
    ;;
  callees)
    shift
    codegraph callees --path "$PROJECT" "$@"
    ;;
  impact)
    shift
    codegraph impact --path "$PROJECT" "$@"
    ;;
  files)
    shift
    cd "$PROJECT" && codegraph files "$@"
    ;;
  explore)
    shift
    cd "$PROJECT" && codegraph context "$@"
    ;;
  node)
    shift
    codegraph node --path "$PROJECT" "$@"
    ;;
  *)
    echo "Usage: $0 {query|context|status|search|callers|callees|impact|files|explore|node} [args...]"
    exit 1
    ;;
esac
