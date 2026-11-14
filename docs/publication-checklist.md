# External publication checklist

This checklist prepares a concrete release. It does not authorize publication or repository-setting changes.

1. Review the exact candidate commit and local acceptance record.
2. Resolve every required failure or explain its exclusion.
3. Complete the owner-arranged volunteer pilot gate.
4. Record authenticated smoke checks for every claimed agent host.
5. Run Linux and native Windows CI before claiming those platforms.
6. Confirm the package name and the owner's PyPI publishing rights.
7. Compare the candidate version, tag, wheel metadata and source archive.
8. Inspect archive contents for local state, credentials and private reports.
9. Confirm installed-wheel UI, skill export and JSON parity checks pass.
10. Review release notes, unsupported hosts and known limitations.
11. Obtain separate approval for the exact push, tag and publication actions.
12. Configure the `pypi` environment with required human reviewers only after that approval.
13. Configure the trusted publisher for this repository and `publish-candidate.yml`.
14. Dispatch the workflow with `publish: false` to prepare artifacts first.
15. Compare prepared artifact hashes with the approved release record.
16. Select the exact version tag for an explicitly approved publication run.
17. Set `publish: true` only for that approved run.
18. Approve the protected environment after checking the downloaded distributions.

The prepared workflow separates build and publishing jobs. Its default is preparation only. Publication requires a matching version tag and explicit manual input.

PyPI trusted publishing needs the repository identity, workflow name and environment to match its configured publisher. Required environment reviewers are configured outside the workflow. See the [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

No workflow has been dispatched and no publisher or environment setting has been changed during this implementation.
