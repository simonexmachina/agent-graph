+++
title = "Google OAuth verification"
description = "Maintainer procedure for verifying AgentGraph with Google."
nav_title = "Google OAuth verification"
nav_hidden = true
section = "Reference"
order = 31
summary = "Prepare and submit AgentGraph for Google OAuth brand and restricted-scope verification."
output = "google-oauth-verification.html"
source_path = "docs-src/google-oauth-verification.md"
+++

This page is a maintainer procedure for publishing AgentGraph's shared Google
Desktop OAuth client. It applies to Google Cloud project `agentswarm-491211`.

## Before submission

Complete these items before asking Google to review the app:

- Host the AgentGraph homepage, privacy policy, and Terms of Service on a custom
  domain controlled by the project. The current `simonexmachina.github.io`
  address cannot be verified through a DNS record owned by AgentGraph.
- Verify the custom domain in [Google Search Console](https://search.google.com/search-console/about)
  using a Google account that is an Owner or Editor of the Cloud project.
- Make the homepage publicly accessible, describe AgentGraph's functionality,
  and link to the same privacy policy and Terms of Service supplied to Google.
- Expand the privacy policy to state data retention and deletion behavior, how a
  user revokes access, and how to contact the project. It must accurately explain
  access, use, storage, and sharing of Google user data.
- Confirm the support email, developer contact email, app name, and logo are
  current in Google Auth Platform.
- Confirm `agentgraph auth google` completes browser consent, token exchange,
  credential storage, and refresh using the packaged OAuth client.
- Publish a releasable AgentGraph package before recording the demonstration.

Google's current [verification requirements](https://support.google.com/cloud/answer/13464321)
and [OAuth branding requirements](https://support.google.com/cloud/answer/15549049)
are authoritative if this checklist differs from the console.

## Review requested scopes

The Google connector currently requests these content scopes:

| Scope | Classification | AgentGraph use |
| --- | --- | --- |
| `gmail.readonly` | Restricted | Read messages and threads for local indexing and search. |
| `drive.readonly` | Restricted | Discover and download the user's existing Drive corpus for local indexing and search. |

The Docs connector exports documents through the Drive API, and the Sheets API
accepts `drive.readonly` for read operations. Do not add `documents.readonly` or
`spreadsheets.readonly` while `drive.readonly` remains requested: Google omits
these redundant scopes from the token response, which also causes strict OAuth
clients to reject the response as a scope change.

Keep `drive.readonly` only if indexing the user's existing Drive corpus remains a
core feature. Google prefers the non-sensitive `drive.file` scope, but that grants
file-by-file access and normally requires a user-driven picker. Document why that
model does not provide AgentGraph's configured-corpus indexing behavior. See
Google's [Drive scope guidance](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Configure Google Auth Platform

1. Open the [AgentGraph Google Auth Platform](https://console.cloud.google.com/auth/overview?project=agentswarm-491211).
2. In **Branding**, enter the app identity, support details, homepage, privacy
   policy, Terms of Service, and verified custom domain.
3. Click **Verify Branding**. Resolve automated findings or request manual review,
   then publish the verified branding within the period shown by Google.
4. In **Audience**, select **External** and move the app to production.
5. In **Data Access**, enable only the scopes that the released application
   requests. Ensure the Gmail, Drive, and Sheets APIs are enabled for the project.
6. Open **Verification Center**, prepare the data-access request, and supply the
   requested scope explanations, documentation links, and demonstration video.
7. Submit the request and monitor both Verification Center and the project Owner,
   Editor, support, and developer-contact email addresses for follow-up questions.

Google requires published branding before sensitive or restricted data-access
verification. Refer to Google's [submission procedure](https://support.google.com/cloud/answer/13461325)
for the current console sequence.

## Scope justifications

Use descriptions consistent with the released application and privacy policy.
Do not claim functionality that is not visible in the demonstration.

### Gmail read-only

> AgentGraph reads email messages and threads for local indexing so the user can
> search and query their own information through a locally running knowledge
> graph. Message bodies are required, so metadata-only access is insufficient.
> Google data is transferred directly between Google and the user's computer and
> is not transmitted to an AgentGraph-operated server.

### Drive read-only

> AgentGraph discovers and reads the user's existing Drive files for local
> indexing and search. The `drive.file` scope is insufficient because it grants
> file-by-file access, while AgentGraph's requested feature indexes the user's
> configured Drive corpus. Data is stored locally and is not transmitted through
> an AgentGraph-operated server.

### Sheets read-only

> AgentGraph reads spreadsheet values so the user can index and search their own
> spreadsheets in a locally running knowledge graph. It does not modify
> spreadsheets, and the data is not transmitted to an AgentGraph-operated server.

Also state that AgentGraph does not use raw or derived Google Workspace data for
advertising or to train or improve generalized AI or machine-learning models.
AgentGraph's declared use must remain consistent with the
[Google Workspace API user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy).

## Demonstration video

Upload one unlisted YouTube video that shows the released application and every
OAuth client included in the project. Record the following in English:

1. Install or run the released AgentGraph package.
2. Run `agentgraph auth google`.
3. Show the complete Google account selection and consent flow.
4. Show `AgentGraph` as the consent-screen app name.
5. Keep the browser address bar visible so Google can see the OAuth client ID.
6. Demonstrate how Gmail, Drive, Docs, and Sheets content is indexed and queried.
7. Exercise every sensitive or restricted scope included in the request.
8. Show that tokens and indexed content are stored on the user's computer.
9. Explain that Google data travels directly between Google and the local
   application, with no AgentGraph-operated data server.

Google publishes the detailed [restricted-scope video and review requirements](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

## Security assessment

`gmail.readonly` and `drive.readonly` require restricted-scope verification.
Google requires an annual third-party security assessment when restricted Google
data is stored on or transmitted through a third-party server.

AgentGraph's released architecture is local-only: Google API calls, tokens,
indexed content, and the SQLite graph remain on the user's computer unless the
user connects another local client. State this explicitly in the submission and
ask the review team to confirm that the server-side security-assessment requirement
does not apply. Google makes the final determination.

## Responding to review

- Reply directly to the verification team's email rather than opening a separate
  request for the same finding.
- Keep console declarations, application behavior, the video, and published
  policies synchronized while review is in progress.
- If Google asks why a narrower scope is insufficient, describe the exact API
  operations and user-visible feature that need the requested scope.
- If scopes or OAuth clients change after approval, check Verification Center
  before releasing the change because another review may be required.
