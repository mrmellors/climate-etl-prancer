# Receiver workspace

> **Builders:** leave this folder as it is. It's for the team that takes over your system
> on November 23.

## Receivers: start here

1. **Make your own copy of the repository.** The builders give your team read access.
   Fork the repository, or clone it and push it to a new repository your team owns,
   starting from the `handoff` tag:

   ```bash
   git clone <builders' repository URL>
   cd <repository>
   git switch -c receiving handoff
   git remote rename origin builders
   git remote add origin <your team's new repository URL>
   git push -u origin receiving
   ```

   From then on, commit only to your copy. The builders keep theirs for their own
   December 1 submission.
2. **Use the builders' team name in commands.** The schema keeps its name after the
   handoff, so if you receive Dasher's system, run `--team dasher` and `SET ROLE
   dasher_write`. Your sign-in can write there from the end of class on November 23.
3. **Start the cold start right away.** Follow the README and runbook exactly as written,
   and record what happens in `log.md` as you go. Ask the builders anything you need, and
   note where you got stuck.

Everything else you owe by Friday, December 4 (your queries, the improvement, this log,
and the video) is under **Receiver work** in the
[project brief](https://stat.cmu.edu/~sgallagh/courses/mads-fall-2026/computing-36614/final-project-framework.html#friday-december-4--receiver-work).
