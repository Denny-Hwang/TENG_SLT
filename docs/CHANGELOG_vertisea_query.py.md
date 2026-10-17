# Query Changelog

## 2026-10-17 - Bounded offline queries - [UNCONFIRMED]

Added lazy context-managed H5 column reads, metadata scans, bounded native pages,
streamed selected CSV and regular-grid aggregation/interpolation. Explicit boot
selection and conservative source segmentation prevent misleading clock joins.
Grid allocation is capped; empty values are NaN with count/coverage/flags.
Finite rolling means reset at gaps; V x mA is labelled estimated power, not
energy from averages. Synthetic tests cover boundaries, chunking and limits.