# Keep LXC lifecycle policy in Ansible

LXC contract compilation, semantic lifecycle planning, and execution remain Ansible-native so the repository retains one architectural center for infrastructure convergence. Lifecycle scenarios, inputs, semantic assertions, and decisions therefore stay in Ansible. Python may select, schedule, launch, report, and test the orchestration of the standalone lifecycle regression launchers, but it may not reimplement lifecycle policy or use Python assertions as a substitute for Ansible-native semantic coverage.

The semantic lifecycle plan is the stable interface and test surface; moving core policy into Python requires demonstrated pressure such as repeated type-related bugs, duplicated decisions, or an unmanageable Ansible scenario matrix rather than anticipated future growth.
