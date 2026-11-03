# LEI Record

LEI Record reads one Legal Entity Identifier, or a legal name, from the public GLEIF API. A parent answer is an official parent record, a reporting exception, or an explicit miss. The plugin does not guess a parent from a name.

## Install and first call

From this directory, with Hermes 0.21.4 or newer:

```
hermes plugins install "file://$PWD" --enable
hermes plugins enable gleif
hermes gleif call lei_lookup --json '{"lei":"335800LUOBQQY1UPKZ54"}'
```

No API key is required. The command prints one JSON object. `parents` is `not_requested` on that call. `golden_copy` is the publish date from the response. `caution` is empty when `registration.status` is `ISSUED` and `entity.status` is `ACTIVE`.

## What the API allows

The LEI data terms of use are at https://www.gleif.org/en/meta/lei-data-terms-of-use/. Access to the API is free. There is no individual contract and no account. The LEI data is under CC0 1.0: https://creativecommons.org/publicdomain/zero/1.0/legalcode. The terms say the data is provided AS IS and that Swiss law applies. Do not present this plugin as a GLEIF product. Do not bypass a technical limit. This plugin does not use the GLEIF trademark or logo. The catalog draft prints the plugin name gleif in large type. It does not reproduce the GLEIF logo or wordmark.

The API description is at https://www.gleif.org/en/lei-data/gleif-api. Reporting exception reasons are listed at https://www.gleif.org/en/lei-data/access-and-use-lei-data/level-2-data-reporting-exceptions-2-1-format. The API documentation at https://documenter.getpostman.com/view/7679680/SVYrrxuU says: Rate limiting is currently set at 60 requests, per minute, per user, for all users. Responses read on 2026-11-03 carried no rate-limit header. This process waits one second between its own requests. It does not retry. A 404 is returned as read and is not requested again.

There is no daily cap. A list call reads page 1, 2, or 3, with five rows on a page. A later page stays unread. The morning list holds at most ten LEIs. A response body over 1,000,000 bytes is not read to the end. That result is `truncated`.

## Parent records

`lei_parents` reads the LEI record first. It then reads the direct parent and the ultimate parent.

An HTTP 200 on the parent URL is an official parent record. Quote that parent LEI and legal name. The reporting-exception URL is not called when the parent record is present.

An HTTP 404 whose body says `Related resource not found` means that related resource is absent. It is not retried. The matching reporting-exception URL is read once. An HTTP 200 there is a reporting exception. Quote `reason` as published. `parent_lei` is null. A reason does not supply a parent name.

When the parent URL and the exception URL both return that same 404, the side is `no_official_record`. That is the explicit miss. A timeout, a redirect, a short body, or any other status is `unknown`. Do not treat `unknown` as a miss. The LEI record can still be `ok` true. `parents_complete` is false when either side is `unknown`.

A missing LEI is a different 404, `lei_not_found`. Parent URLs are not called.

`lei_lookup` with `legal_name` returns candidates. A name that differs after case and spacing are folded, including an accent, stays a candidate. That call does not request parents. `lei_search` returns legal-name candidates from the fuzzy response and does not request a parent or an LEI record. An empty candidate list says that the fuzzy search returned no legal-name candidate.

`lei_children` lists direct child records. `lei_isin` maps one ISIN to LEI records, or lists ISINs on one LEI. An empty complete page is the only zero. A page with a further link is not the full list.

When `registration.status` is not `ISSUED`, or `entity.status` is not `ACTIVE`, the record includes one `caution` line. A code outside the published lists is quoted that way. The golden copy date is `golden_copy`.

## What is sent, and what stays here

The LEI, legal name, or ISIN you pass is sent to `api.gleif.org` over HTTPS. Nothing else is sent. Redirects are not followed. An HTTP proxy in the environment is not used. The read tools do not write a file.

The tools start enabled on every surface. An empty gateway allowlist still leaves them enabled, so a person who can message that surface can call them. Turn one surface off with `hermes tools disable gleif --platform telegram`. The CLI call still runs after that.

The watch file under `plugin-data/gleif` stays on this machine. It stores the LEI and the last registration status, entity status, and golden copy date. Each directory is opened from the filesystem root. A symlink under the Hermes home is refused, and the message names `symlink`. The first directory of an absolute path may be an operating-system alias. On macOS, `/tmp` and `/var` are aliases of a private directory. A home under those aliases is written through the real directory. A symlink on a later directory, or on the file itself, is refused.

## Morning watch

This plugin does not set approval-card text. The morning job is a CLI command. Before you run it, read the watched LEI list, the 08:00 schedule, and the local-only delivery. Those are the whole change. The job compares saved status values. It does not delete a record at the API.

```
hermes gleif watch add 335800LUOBQQY1UPKZ54
hermes gleif watch list
hermes gleif schedule
hermes gleif status
hermes gleif unschedule
```

`schedule` accepts only `local`. Delivery is local only. Any other deliver target is refused before a job is created. It writes `scripts/gleif-watch.py` and creates one cron job named `gleif-watch`. The schedule is 08:00. Hermes uses the profile timezone when one is set, and otherwise the machine local time. The run has no model turn and spends 0 tokens. The job does not fire until a scheduler is serving this profile. `hermes cron status` says the jobs will not fire. On the default profile it prints `hermes --profile default gateway install`. `hermes cron list` prints `hermes gateway install`. Local delivery keeps a printed line under `cron/output` and sends nothing to a chat. The first successful read stores a baseline and prints no line. A later morning prints one line when `registration.status` or `entity.status` changed, with the golden copy date and the caution line when there is one. An empty script sends nothing. A failed read keeps the saved status and prints that the LEI was not read.

`unschedule` removes the cron job and `scripts/gleif-watch.py`. The watch file remains.

After `hermes plugins remove`, three leftovers remain: the cron job, `scripts/gleif-watch.py`, and `plugin-data/gleif/watch.json`. Copy the id from `hermes gleif status` or from `hermes cron list` before you remove the plugin. `hermes cron status` prints the active job count and the next run. It does not print the id. Stop the leftover job with `hermes cron remove <id>`. On a profile other than `default`, use the `hermes -p <profile>` prefix printed by `status`. Delete `scripts/gleif-watch.py` and `plugin-data/gleif/watch.json` if they are still there. `hermes cron remove` with no id exits 2 and the job stays.
