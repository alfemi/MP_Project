# StreamSync User Story Coverage

## 1.5

| ID | Status | Evidence in the app | Notes / next action |
|---|---|---|---|
| R1.1 | Implemented | `/register/`, `web/templates/web/register.html` | Registration form includes user data, profile preferences and terms checkbox. |
| R1.2 | Implemented | `web.views.register` | User submits registration data through POST. |
| R1.3 | Implemented | `web.views.register`, `FunctionalUser` constraints | Validates required data, password policy, uniqueness, preferences and terms acceptance. |
| R1.4 | Implemented | `web.views.register` | Creates `FunctionalUser` after validation. |
| R1.5 | Implemented | `InfoUser`, registration preferences | Initial configuration is collected in registration and profile is created. |
| AD2.1 | Implemented | `/profile/`, `web.templates.web.profile` | Authenticated users access profile editing. |
| AD2.2 | Implemented | `ProfileUpdateForm`, `PasswordChangeForm` | Users edit profile data, preferences and password. |
| AD2.3 | Implemented | `web.views.profile` | Profile changes are validated and saved. |
| B3.1 | Implemented | `/catalog/`, `/home/`, search input `title` | Users and guests can enter search text. |
| B3.2 | Implemented | `_build_api_filters`, `StreamApiService.get_movies/get_series` | Search/filter parameters are sent to the catalog source. |
| B3.3 | Implemented | `web/templates/web/home.html` | Matching catalog cards are rendered. |
| B3.4 | Implemented | `/content/<type>/<id>/` | Selecting a result opens the detail page. |
| G4.1 | Partial | `/favorites/`, `web/templates/web/favorites.html` | Implemented as “Les meves llistes” with default “Llista de favorits”. |
| G4.2 | Prototype | Detail recommendations, favorites page empty state | Genre-based recommendations exist; full list organization suggestions are future work. |
| G4.3 | Partial | `toggle_favorite` | Users can add/remove items from the default favorites list. Custom list editing is not implemented. |
| G4.4 | Partial | `FavoriteContent` unique constraint | Favorite changes are validated by content type/id and uniqueness. |
| G4.5 | Implemented | `ContentInteraction` records view/favorite add/remove | Traceability exists for detail views and favorite changes. |
| AC7.1 | Prototype | `StreamApiService.get_all_data` | API consultation happens on demand; no scheduler configured locally. |
| AC7.2 | Prototype | `StreamApiService` deduplicates external data | Compares providers by content ID for current responses, not persistent catalog diffing. |
| AC7.3 | Not implemented | — | No internal persisted catalog update pipeline; out of final-project scope. |
| AC7.4 | Prototype | `ApiFailureEvent`, dashboard status | API status/failures are visible; no completed sync confirmation workflow. |
| IE10.1 | Implemented | `/directors/` period/objective filters | Directors select period and strategic objective. |
| IE10.2 | Implemented | `web.analytics` | Aggregates usage, favorites, interactions and catalog quality. |
| IE10.3 | Implemented | `/directors/` “PUC 10 — Informe estratègic” | Structured strategic report with evidence, risks, opportunities and scenarios. |
| IPR12.1 | Partial | `/directors/` generated on request | Periodic report can be generated manually; real scheduler is not configured. |
| IPR12.2 | Implemented | `web.analytics.build_periodic_report_summary` | Aggregated usage and quality indicators are calculated. |
| IPR12.3 | Implemented | `/directors/` “PUC 12 — Informe periòdic de rendiment” | Summary/report renders with status and warnings. |

## 2.3

| ID | Status | Evidence in the app | Notes / next action |
|---|---|---|---|
| S1.1 | Not implemented | — | Requires platform notification/webhook infrastructure, out of local final scope. |
| S1.2 | Prototype | `StreamApiService.get_all_data` | Current catalog reads latest provider data on demand; no persisted title state. |
| S1.3 | Prototype | Multi-provider deduplication by ID | Availability across providers can be inferred from current API responses only. |
| S1.4 | Not implemented | — | User notification system for removals is out of scope. |
| S1.5 | Partial | `ApiFailureEvent` admin records API incidents | Catalog synchronization change log is not fully implemented. |
| V2.1 | Prototype | `STREAM_APIS` API keys, request headers | Credentials are used for calls; no separate credential linking UI. |
| V2.2 | Partial | `ApiFailureEvent`, operational dashboard | Failures/timeouts are recorded for technical review. |
| V2.3 | Not implemented | — | Contract permission model is out of scope. |
| V2.4 | Not implemented | — | API version registry is not stored. |
| V2.5 | Partial | `ApiFailureEvent` monitoring | Connection errors and status codes are tracked. |
| A3.1 | Implemented | `/directors/` protected dashboard | External/director role can view aggregated consumption data. |
| A3.2 | Implemented | `/directors/?period=&objective=` | Filters support period and report objective. |
| A3.3 | Prototype | “Informe estratègic” scenarios | Interest prediction is presented as orientative, not a robust ML prediction. |
| A3.4 | Partial | PUC 12 report and CSV export | Periodic report exists on demand; no scheduled publication. |
| A3.5 | Not implemented | — | Partner query audit log is not implemented. |
| R4.1 | Partial | `ApiFailureEvent.severity`, operational dashboard | Degradation is recorded; impact calculation is basic. |
| R4.2 | Not implemented | — | Automatic mitigation requires deployment/runtime infrastructure. |
| R4.3 | Partial | `ApiFailureEvent.record_failure` groups repeated failures | Related identical API failures are aggregated. |
| R4.4 | Not implemented | — | Public status page automation is out of scope. |
| R4.5 | Not implemented | — | Automatic rollback infrastructure is out of scope. |
| C5.1 | Not implemented | — | Config dry-run simulator is out of scope. |
| C5.2 | Not implemented | — | Progressive config rollout is out of scope. |
| C5.3 | Not implemented | — | Automatic config revert requires infrastructure. |
| C5.4 | Not implemented | — | Ticket/MFA/versioned config workflow is out of scope. |
| C5.5 | Not implemented | — | Scheduled config changes are out of scope. |
