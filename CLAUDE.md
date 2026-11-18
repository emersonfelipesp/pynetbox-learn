# pynetbox-learn agent guide

This repository is the public Emerson fork of pynetbox. Keep library behavior,
package identity and the upstream Apache-2.0 license intact. The corresponding
Gitea repository is empty and is used for task tracking only; do not populate it
or copy private infrastructure metadata into this public source.

## CI contract

The public quality workflow retains all nine Python 3.10/3.11/3.12 and NetBox
4.0/4.1/4.2 combinations. Each row runs the original complete Black check and
pytest command. Docker-backed integration tests must run on an ephemeral hosted
runner with Git, Docker and Compose available. Never point these fixtures at a
managed NetBox system or a shared Docker host: their cleanup intentionally
matches test container, network and volume names.

The integration fixture explicitly starts Compose in detached mode, then uses
its existing 300-second NetBox HTTP readiness check. Do not let a dependency's
shorter default container-health wait preempt first-boot migrations. Keep all
real API tests, the existing readiness deadline and normal cleanup intact.

Only superseded pull-request runs cancel. Master push quality finishes
independently. Python and NetBox matrix complete succeeds only after every
original matrix row succeeds. A skipped, cancelled or failed producer is not a
passing quality result. Master-only push filtering already existed; do not claim
that this change removes duplicate feature-push jobs.

Use supported Ubuntu 24.04 hosted images, immutable action references and a pip
cache keyed by all dependency inputs. Checkout does not persist credentials and
fetches complete source metadata for setuptools-scm. The release-only publisher
is unchanged; CI work does not authorize releases, package publication or tags.

Run the original Black check and the full unit suite locally in a task-owned
virtual environment. Full integration qualification requires the actual hosted
matrix. Keep all existing tests and assertions. Run a per-function complexity
audit for executable changes and preserve full evidence. Require genuine
exact-candidate checks before a normal squash merge; never bypass branch
protection or record the user's adversarial-review waiver as a passing review.
