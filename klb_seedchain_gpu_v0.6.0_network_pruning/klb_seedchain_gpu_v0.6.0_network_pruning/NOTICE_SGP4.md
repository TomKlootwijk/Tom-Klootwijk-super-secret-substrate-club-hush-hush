# SGP4 provenance notice

The mathematical implementation in this package follows the SGP4/SDP4 family
published and maintained through the Vallado/CSSI reference work. Development
and verification used the public reference material and verification vectors
commonly distributed with that implementation family.

Aholinch's multi-language SGP4 repository was also consulted as a practical C
reference. That repository declares its code under the Unlicense/public-domain
dedication and explains that its implementation is based on the CSSI code and a
US Government standard. No warranty is provided by those sources or by this
package.

Reference repository:

```text
https://github.com/aholinch/sgp4
```

The package-specific OMM/KSGP1 adapters, lineage/timeline format, direct query
integration, tests, and benchmark harness are distributed under the root MIT
license. The underlying SGP4 theory, reference history, and third-party data
retain their respective provenance.
