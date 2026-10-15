# Branching Strategy

This document outlines the branching strategy for this repository. The goal is to maintain the stability of the `main` branch while allowing for organized development of new features and fixes.

## Table of Contents
- [1. The `main` and `stage` Branches](#1-the-main-and-stage-branches)
- [2. Development Branches](#2-development-branches)
  - [Branch Naming Convention](#branch-naming-convention)
- [3. The Workflow](#3-the-workflow)

## 1. The `main` and `stage` Branches

The `main` branch represents production. Every merge to `main` deploys the `prod` stack.

The `stage` branch is where finished work lands first, and it is the repository's default branch. Every merge to `stage` deploys the `stage` stack, where changes are checked before they reach production.

* **Rule:** **Direct commits to `main` and `stage` are strictly prohibited.** Changes reach `stage` through a Pull Request (PR), and `stage` reaches `main` through a PR from `stage` to `main`.
* Both branches require the `test` check to pass before a PR can merge.

## 2. Development Branches

All new work, including features, bug fixes, and experiments, must be done on a separate branch. This keeps the `main` branch clean and ensures that incomplete code doesn't break the application.

### Branch Naming Convention

Use the following prefixes to keep branch names clear and organized:

* **`feature/`**: For adding, refactoring, or removing a feature.
    * *Example:* `feature/add-sqs-support`
* **`fix/`**: For fixing a bug in the production code.
    * *Example:* `fix/correct-slack-message-format`
* **`chore/`**: For maintenance tasks that don't change application code.
    * *Example:* `chore/update-readme` or `chore/add-gitignore`

## 3. The Workflow

Here is the step-by-step process for making a change:

1.  **Create a New Branch:**
    Before starting work, pull the latest changes from the `stage` branch. Then, create a new branch from `stage` with a descriptive name.
    ```bash
    # Get the latest code
    git checkout stage
    git pull origin stage

    # Create your new feature branch
    git checkout -b feature/my-new-feature
    ```

2.  **Commit Your Changes:**
    Make your code changes on your new branch. Commit your work frequently with clear and concise commit messages.
    ```bash
    git add .
    git commit -m "feat: Add initial logic for the new feature"
    ```

3.  **Open a Pull Request (PR):**
    When you are ready for your changes to be reviewed, push your branch to the remote repository and open a Pull Request to merge your branch into `stage`.
    ```bash
    git push origin feature/my-new-feature
    ```
    In your PR description, clearly explain the "what" and "why" of your changes. If it fixes an issue, be sure to reference it.

4.  **Code Review:**
    At least one other collaborator must review and approve your Pull Request before it can be merged. This ensures code quality and shared knowledge.

5.  **Merge and Clean Up:**
    Once the PR is approved, the changes can be merged into `stage`, which deploys them to the `stage` stack. After merging, delete your development branch to keep the repository tidy.

6.  **Promote to Production:**
    When the changes work on the `stage` stack, open a PR from `stage` to `main` and merge it with a merge commit (not a squash), so the two branches keep the same history. Merging it deploys to `prod`. The `/promote` skill does this step (see [Working with AI Agents](Working%20with%20AI%20Agents.md)).
