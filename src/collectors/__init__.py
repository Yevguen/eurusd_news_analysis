"""Automated data collectors - intentionally NOT implemented.

The January 2024 research slice was assembled by manual transcription from
official release pages, followed by the structured source audit in
``config/historical_release_audits/``. No code in this repository downloads
or scrapes third-party data.

Any future collector must:

1. target only sources classified ``permitted_with_attribution`` in
   ``config/data_sources.yaml`` (or store results privately);
2. record retrieval URL and retrieval date for every record;
3. write ``HistoricalRelease`` records with an explicit ``data_origin``;
4. pass the publication-safety guard before anything is committed.
"""
