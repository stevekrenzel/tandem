# Guided walkthroughs

Inspect the relevant live code and Git changes before choosing a route. Open one
coherent stop, explain its role with concrete file and line references, and wait
for the user's next step or question. Adapt the pace if they ask for an
uninterrupted tour. If no topic was supplied, ask what they want to explore.

For a branch or PR tour, identify the intended base from Git/PR metadata and use
its merge-base commit for the comparison. Confirm that the checkout matches the
PR before claiming the visible files are its implementation. Use `HEAD` for
local uncommitted changes.

A walkthrough does not authorize edits, saves, branch changes, or overwriting
buffers. If the user requests implementation, switch to that coding task while
preserving their unsaved work.

When finished, clear the temporary annotations and comparison pane.
