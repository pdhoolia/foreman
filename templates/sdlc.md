# Development workflow

This project runs on the foreman plugin. The plugin's README holds the conventions:
plan head lines, task file bullets, plain words, decision records, the control room and
the roles. This file holds only what is specific to this project. When the two
disagree, this file wins for this project; change the README when a rule should hold
for every project.

## Roles here

| Role | Who |
| --- | --- |
| Owner | <name: sets priorities, approves decisions, merges> |
| Track coordinators | one session per active track |
| Program session | one thin session |
| Developers | one session per task, each in its own checkout and branch |
| Reviewers | a read-only pass per pull request, dispatched by the coordinator |

## Checks before a push

<The command a contributor runs before `git push`, and what it covers. A check that
cannot run is named in the pull request; it is never counted as a pass.>

## Branches, commits and pull requests

<The branch name rule, the commit message rule and the pull request shape this project
uses, or a link to the file that holds them.>

## Project-specific rules

<Anything else: demos, data that must stay private, services that tests need.>
