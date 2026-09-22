This inventory records the feature audit against the semantic suite introduced in
`8794ef5d0056a5cc686e4de0e53eb9b8734ccd98` and the subsequent tests. Coverage is
assessed by observable outcomes for learners, authors, administrators, and
operators. A successful response alone does not establish that work was saved,
progress survived an update, or a service became usable.

| Feature area | Existing coverage reviewed | Gaps addressed by this audit |
| --- | --- | --- |
| Accounts and profiles | Authentication, identity lookup, visibility, SSH keys, account changes, and activity | Registration profile persistence, custom fields, email policies, confirmation and recovery with mail enabled |
| Learning and feedback | Solve submission, flags, required challenges, visibility windows, progression, surveys, and resources | Durable survey values and history, imported feedback attribution, publishing and reopening lessons, reading-only modules |
| Authoring and imports | Specification validation, field inheritance, import permissions, administration, updates, transfers, deletion, and custom pages | Whole-dojo lesson inheritance, optional imported exercises, reordered and transferred progress, refreshed module lessons, personalized downloads, authorized lesson JavaScript |
| Courses | Rosters, identity linkage, assessment rules, grade calculations, authorization, date filters, and exports | Relinking and roster changes applied to existing coursework, hidden students in instructor exports, CSV/JSON identity, ordering, and timestamp agreement |
| Browsers | Workspace controls, terminal/editor/desktop access, invitations, survey forms, and profile progress | Progression without reload, correcting a rejected flag, solve updates across tabs, newer frontend reading and session workflows |
| Awards, social features, and discovery | Belts, emoji, custom awards, backfill and pruning, scores, crews, feeds, search, Discord, research, and SenSAI | Configured Discord OAuth linking, relinking, failure recovery, and conflicting associations |
| Managed LLM access | No feature tests found | Credential permission and renewal, usage aggregation, provider recovery, client configuration, personal authentication precedence, opt-out, and CLI usage reporting |
| Workspace access and storage | Startup/replacement, practice, sharing, tokens, proxies, SSH/SFTP/SCP, quotas, snapshots, overlays, and node placement | Custom application HTTP round trips, stale service recovery and stopping, restorable home resets, valid snapshot imports, SSH reconnection, and keyboard-driven challenge selection |
| Operators and external backends | CLI configuration, database restore, worker events and retries, monitoring, image protection, and multinode operation | Builder failure readiness, encrypted cloud backups and upload failures, all-node image distribution and recovery, partial watchdog failures, and Mac workspace adapter behavior |

The new browser tests locate controls and inspect visible state to establish
functionality; they do not compare rendered HTML or styling. API and storage tests
check persisted data, attribution, ordering where meaningful, and behavior after
subsequent actions. External service tests use local providers or simulated
transports while running the real client, handler, or command. Fixtures restore
changed configuration and use separate users, dojos, volumes, and home directories.

`tiers.py` assigns workflow tests to the semantic selection and retains contract,
integration, or unit classifications for checks at those levels. Topology-sensitive
SSH reconnection and custom application proxy tests also participate in the
multinode selection. Run the semantic selection with:

```sh
./deploy.sh -N -t -- -m semantic
```

Controlled provider tests establish the dojo's behavior at the service boundary.
They do not exercise real Discord guilds, vendor inference or billing, S3, or a
physical Mac. VSCode tunnel provisioning and authentication still require a
separate external account environment. The browser additions exercise core newer
frontend workflows; they do not claim every frontend interaction is covered.
