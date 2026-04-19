# Multilingual Media Stack Design

**Date:** 2026-04-19  
**Status:** Approved

## Context

The existing stack (Seerr → Radarr/Sonarr → Jellyfin) works well for English content. This design extends it to support:

- Multiple content languages: French (Quebec/France), Asian Drama (Korean/Japanese/Chinese), Anime, Foreign catch-all, future Spanish
- Automatic routing of requests to the correct root folder via Seerr override rules — no user trust required
- Multilingual subtitles (EN/FR/ES) on all content via Bazarr
- Separate Jellyfin libraries per content category, with French libraries using French metadata
- Anime on dedicated *arr instances due to incompatible Trash Guide custom format profiles

## Disk Structure

```
/data/
  media/
    movies/
      en/           # English + Western animation movies
      fr/           # French movies
      foreign/      # Non-EN/FR/ES, non-anime movies
      anime/        # Anime movies
    tv/
      en/           # English + Western animation series
      fr/           # French series
      asian/        # Asian Drama series (non-anime)
      foreign/      # Non-EN/FR/ES, non-anime, non-Asian series
      anime/        # Anime series
```

Adding Spanish later = `/data/media/movies/es/` and `/data/media/tv/es/` with no structural changes.

## *arr Instances

| Instance | Root folders |
|---|---|
| Radarr main | `movies/en`, `movies/fr`, `movies/foreign` |
| Radarr anime | `movies/anime` |
| Sonarr main | `tv/en`, `tv/fr`, `tv/asian`, `tv/foreign` |
| Sonarr anime | `tv/anime` |

## Seerr Routing

Single Seerr instance. Override rules use TMDB `original_language` and genre. Rules apply to non-admin users automatically — no manual choice required. Admin bypasses rules and picks manually only for edge cases.

Rules evaluated most-specific-first:

| Condition | Destination |
|---|---|
| Animation genre + `ko\|ja\|zh` | Radarr anime / Sonarr anime |
| `original_language = fr` | `movies/fr` or `tv/fr` |
| `original_language = ko\|ja\|zh` | `movies/foreign` or `tv/asian` |
| `original_language = en` | `movies/en` or `tv/en` |
| default service (no rule match) | `movies/foreign` or `tv/foreign` |

Setting the default service to Foreign acts as a catch-all — Italian, German, Portuguese, and any other unspecified language routes there automatically without listing every language code.

Sister's account: restricted to French service profiles only — she cannot accidentally route to the wrong library.

Future Spanish family: same pattern, restrict their accounts to Spanish profiles when added.

## Quality Profiles (Notifiarr)

| Profile | Applied to | Standard |
|---|---|---|
| Main HD | Radarr main, Sonarr main (en/fr/foreign) | Trash Guide HD |
| Asian Drama | Sonarr main `tv/asian` | Lower bitrate acceptable, 1080p WEB-DL |
| Anime | Radarr anime, Sonarr anime | Trash Guide anime profiles |

## Subtitles (Bazarr)

Bazarr is already deployed. Configuration changes:

- **Languages:** EN, FR, ES — downloaded proactively on all content
- **Priority order:** EN → FR → ES
- **Providers:** OpenSubtitles.com (primary, requires free account) + Subdl (secondary, best modern multilingual coverage)
- Applies to all libraries including anime and Asian Drama

## Jellyfin Libraries

| Library name | Path | Metadata language |
|---|---|---|
| Movies | `movies/en` | English |
| French Films | `movies/fr` | French |
| Foreign Films | `movies/foreign` | English |
| Anime Movies | `movies/anime` | English |
| TV Shows | `tv/en` | English |
| French TV | `tv/fr` | French |
| Asian Drama | `tv/asian` | English |
| Foreign TV | `tv/foreign` | English |
| Anime | `tv/anime` | English |

French libraries (`movies/fr`, `tv/fr`) use French TMDB metadata — French titles, descriptions, posters — for the French-speaking user's experience. All other libraries use English metadata.

## User Access Summary

| User | Seerr profiles visible | Jellyfin |
|---|---|---|
| Admin (you) | All | All libraries |
| French sister | French profiles only | All libraries (French libs feel native) |
| Future Spanish family | Spanish profiles only | All libraries |

## Future Extensions

- **Spanish content:** Add `movies/es`, `tv/es` root folders + `original_language = es` override rule + Spanish Jellyfin libraries. Zero restructuring.
- **Anime already isolated:** Radarr anime + Sonarr anime ready for full Trash anime profile configuration independently.
- **Comics/Manga:** Already handled by Kapowarr/Kaizoku stack, separate concern from this design.

## Verification

End-to-end test sequence:

1. Request a French film as sister's account → lands in `movies/fr`, appears in "French Films" Jellyfin library with French metadata
2. Request a Korean drama as admin with Asian Drama profile → lands in `tv/asian`, appears in "Asian Drama" Jellyfin library
3. Request a known anime series → routes to Sonarr anime, lands in `tv/anime`
4. Confirm Bazarr downloads EN + FR + ES subtitles for a newly added item in each library
5. Request a non-EN/FR/ES/Asian film → lands in `movies/foreign`
6. Confirm sister cannot see non-French service profiles in Seerr
