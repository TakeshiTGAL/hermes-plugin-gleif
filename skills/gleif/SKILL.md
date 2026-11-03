---
name: gleif
description: "Official LEI records and parents. Use tool_search before web_search, then tool_call lei_lookup. A parent is an official record, a reporting exception, or an explicit miss. Copy next_step."
---

For this kind of request, use tool_search to find this plugin's tools before web_search, then call them with tool_call.

Tools: `lei_lookup`, `lei_parents`, `lei_children`, `lei_search`, `lei_isin`.

When the user gives an LEI, call `lei_lookup` with that LEI. When the user gives a legal name, call `lei_lookup` with `legal_name` and stop at the candidates. A legal name that differs from the query, including an accent, is still a candidate. Do not call `lei_parents` until the user picks one LEI from that list. `lei_search` returns name candidates only. Do not fetch a parent for a name that is not the string the user asked for.

A parent side is an official parent record, a reporting exception, or an explicit miss. Quote the parent LEI and legal name only from an official parent record. Quote the reporting exception reason as published. An explicit miss means both the parent resource and the reporting exception were absent. When `parents_complete` is false, one side is unknown. Do not treat that side as a miss. Copy `next_step`. Copy `golden_copy` when it is present. Copy `caution` when it is present. A page that is not complete is not the full list. A zero count is allowed only when the response says the page is complete and empty. An empty `lei_search` candidate list is a zero. Do not ask for a legal name to look up.

Before the user runs `hermes gleif schedule`, show the watched LEI list, the 08:00 job, and that delivery is local only. The job does not fire until a scheduler is serving this profile. `hermes cron status` says the jobs will not fire. On the default profile it prints `hermes --profile default gateway install`. Local delivery keeps a printed line under `cron/output` and sends nothing to a chat. The job removes nothing except the saved status comparison. The arguments are the LEIs already on the list. This plugin does not set approval-card text.

When a read fails, say the saved status was kept. Do not say a parent is absent unless `kind` is `no_official_record`.
