# Branching Strategy

This document outlines the branching strategy for this repository. The goal is to maintain the stability of the `main` branch while allowing for organized development of new features and fixes.

## 1. The `main` Branch

The `main` branch is the single source of truth and represents the production-ready code.

* **Purpose:** Contains stable, tested, and deployable code. Every commit on `main` should, in theory, be safe to deploy.
* **Rule:** **Direct commits to the `main` branch are strictly prohibited.** All changes must be merged into `main` through a Pull Request (PR).

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
    Before starting work, pull the latest changes from the `main` branch. Then, create a new branch from `main` with a descriptive name.
    ```bash
    # Get the latest code
    git checkout main
    git pull origin main

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
    When you are ready for your changes to be reviewed, push your branch to the remote repository and open a Pull Request to merge your branch into `main`.
    ```bash
    git push origin feature/my-new-feature
    ```
    In your PR description, clearly explain the "what" and "why" of your changes. If it fixes an issue, be sure to reference it.

4.  **Code Review:**
    At least one other collaborator must review and approve your Pull Request before it can be merged. This ensures code quality and shared knowledge.

5.  **Merge and Clean Up:**
    Once the PR is approved, the changes can be merged into `main`. After merging, delete your development branch to keep the repository tidy.