#!/usr/bin/env python3
"""Build machine-readable UGTS-KC 3.6.3 SARA delta assets."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts36.canonical import attach_content_hash  # noqa: E402
from ugts36.model import Substrate  # noqa: E402
from ugts36.sara363 import (  # noqa: E402
    build_reference_sara363_certificate,
    decode_segwit_address,
    estimate_uniform_search,
)
from ugts36.sara_runtime import SARARuntime  # noqa: E402

VERSION = "3.6.3"
PROFILE_ID = "sara363.seed-address-referential-algebra-v1"
TARGET_ADDRESS = "bc1q7ydrtdn8z62xhslqyqtyt38mm4e2c4h3mxjkug"
WORDLIST_SHA256 = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def operator_catalog() -> list[dict[str, Any]]:
    raw = [
        ("sara363.profile.v1", "Profile", "Seed-address referential algebra", "Typed BIP39/BIP32/BIP84/Bech32 profile with public-only certificates and an authorization gate.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.governance.evidence-boundary", "Governance", "Source and standards boundary", "Separate BIP-defined transformations, engineering glue, public fixtures, metrics and rejected attack scopes.", "RETAIN", "Enforced"),
        ("sara363.security.secret-class", "Security", "Secret/public classification", "Entropy, mnemonic, passphrase, seed, private scalar and chain code are secret; addresses, scripts and test vectors are public.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.wordlist.commitment", "Encoding", "2048-word list commitment", "Bind the selected BIP39 wordlist by count, order, uniqueness, normalization and SHA-256 digest.", "RETAIN", "Exact"),
        ("sara363.entropy.input", "Encoding", "Computer-generated entropy input", "Admit only ENT in {128,160,192,224,256}; do not treat arbitrary user sentences as entropy.", "RETAIN", "Exact"),
        ("sara363.checksum.prefix", "Encoding", "BIP39 checksum prefix", "CS=ENT/32 and checksum bits are the first CS bits of SHA-256(entropy).", "RETAIN", "Exact"),
        ("sara363.bits.concat", "Encoding", "Entropy-checksum concatenation", "Append checksum bits to entropy before word segmentation.", "RETAIN", "Exact"),
        ("sara363.bits.segment11", "Encoding", "Eleven-bit segmentation", "Split ENT+CS into ordered 11-bit cells, each in [0,2047].", "RETAIN", "Exact"),
        ("sara363.words.lookup", "Encoding", "Word-index lookup", "Map each 11-bit cell to one word in the committed list.", "RETAIN", "Exact"),
        ("sara363.words.cell-complex", "Topology", "Ordered word-cell complex", "Represent the mnemonic as a 1D path of labeled 11-bit cells whose adjacency preserves word order.", "TRANSLATE", "Specified"),
        ("sara363.mnemonic.checksum-hinge", "Event calculus", "Mnemonic checksum hinge", "A mnemonic is admitted only when observed checksum cells equal the entropy-hash prefix.", "TRANSLATE", "Implemented"),
        ("sara363.text.nfkd", "Encoding", "Unicode NFKD normalization", "Normalize mnemonic and passphrase as required before seed derivation.", "RETAIN", "Implemented"),
        ("sara363.seed.pbkdf2", "Cryptography", "Mnemonic-to-seed transition", "PBKDF2-HMAC-SHA512 with 2048 iterations, 64-byte output and salt 'mnemonic'+passphrase.", "RETAIN", "Implemented"),
        ("sara363.seed.no-serialization", "Security", "Seed nonserialization", "Seed bytes are transient and excluded from substrate definitions, traces, certificates and package data.", "ENGINEERING-DERIVED", "Enforced"),
        ("sara363.bip32.master", "Cryptography", "BIP32 master node", "HMAC-SHA512 with key 'Bitcoin seed' creates a private scalar and 32-byte chain code.", "RETAIN", "Implemented"),
        ("sara363.bip32.node", "Topology", "Extended-key tree node", "Node state is key material plus chain code, depth, parent fingerprint and child number.", "RETAIN", "Implemented"),
        ("sara363.bip32.normal-edge", "Topology", "Normal derivation edge", "Indices below 2^31 admit private and public child derivation under BIP32 rules.", "RETAIN", "Private path implemented"),
        ("sara363.bip32.hardened-edge", "Topology", "Hardened derivation edge", "Indices at or above 2^31 require parent private material and block public-parent derivation.", "RETAIN", "Private path implemented"),
        ("sara363.path.parser", "Encoding", "Derivation-path parser", "Parse m/... with explicit hardened markers and uint32 bounds.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.path.bip44", "Information architecture", "Five-level account hierarchy", "Purpose/coin/account/change/index are distinct typed path levels.", "RETAIN", "Specified"),
        ("sara363.path.bip84", "Information architecture", "Native P2WPKH derivation policy", "Use m/84'/coin'/account'/change/index for BIP84 accounts.", "RETAIN", "Implemented"),
        ("sara363.ec.secp256k1", "Cryptography", "secp256k1 public projection", "Map a valid scalar to a curve point without exposing a signing API.", "RETAIN", "Reference implementation"),
        ("sara363.pubkey.compressed", "Encoding", "Compressed public key", "Serialize a curve point as parity prefix plus 32-byte x coordinate.", "RETAIN", "Implemented"),
        ("sara363.hash.hash160", "Cryptography", "HASH160 commitment", "RIPEMD160(SHA256(compressed public key)) yields the 20-byte P2WPKH witness program.", "RETAIN", "Implemented"),
        ("sara363.script.p2wpkh", "Relation", "P2WPKH script relation", "Witness v0 with a 20-byte key hash maps to scriptPubKey 0x0014{program}.", "RETAIN", "Implemented"),
        ("sara363.address.convertbits", "Encoding", "Eight-to-five-bit regrouping", "Convert witness-program bytes into 5-bit Bech32 data groups with canonical padding.", "RETAIN", "Implemented"),
        ("sara363.address.hrp", "Encoding", "Human-readable prefix", "Bind the network namespace through HRP such as bc or tb.", "RETAIN", "Implemented"),
        ("sara363.address.bech32", "Encoding", "Bech32 checksum shell", "Witness version 0 addresses use the BIP173 polymod constant.", "RETAIN", "Implemented"),
        ("sara363.address.bech32m", "Encoding", "Bech32m checksum shell", "Witness versions 1-16 use the BIP350 polymod constant.", "RETAIN", "Implemented"),
        ("sara363.address.decode", "Query", "Public address decoder", "Validate case, HRP, checksum family, witness version, program length and script projection.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.address.classify", "Query", "Witness-program classifier", "Classify v0/20 as P2WPKH, v0/32 as P2WSH and v1/32 as a Taproot-compatible form.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.address.noninverse", "Security", "Non-reversibility boundary", "Address decoding exposes a script commitment, not a private key, seed or spend authority.", "CORRECTED", "Enforced"),
        ("sara363.fixture.public-address", "Fixture", "User-supplied public address fixture", "Use the supplied bc1q address only for format, checksum, witness-program and scriptPubKey validation.", "BOUNDED", "Verified"),
        ("sara363.audit.self-owned", "Audit", "Self-owned known-seed audit", "Permit deterministic backup verification only when the operator already possesses the mnemonic or seed.", "BOUNDED", "Policy"),
        ("sara363.audit.watch-only", "Audit", "Watch-only public audit", "Permit address/descriptor parsing and public derivation evidence without spend authority.", "BOUNDED", "Policy"),
        ("sara363.audit.authorization-gate", "Governance", "Authorization gate", "Every audit declares a scope and is rejected if any operation targets private keys, third-party secrets or funds.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.audit.forbidden-search", "Governance", "Forbidden-target rejection", "Reject mnemonic enumeration, passphrase spraying, private-key scanning and address-targeted preimage search.", "REJECT", "Enforced"),
        ("sara363.audit.no-network", "Security", "No-network reference runtime", "The reference implementation performs no blockchain queries, balance lookups or remote calls.", "ENGINEERING-DERIVED", "Enforced"),
        ("sara363.audit.no-signing", "Security", "No-signing reference runtime", "The reference implementation exposes no transaction signing, PSBT mutation, broadcast or funds-transfer path.", "ENGINEERING-DERIVED", "Enforced"),
        ("sara363.metric.uniform-search", "Metric", "Uniform search-space estimator", "Report 2^b candidates, 2^(b-1) expected guesses and time at a declared optimistic rate; do not enumerate.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.metric.bip39-valid-space", "Metric", "Valid mnemonic keyspace", "A 12-word BIP39 space contains 2^128 valid mnemonics; checksum filtering does not reduce the encoded entropy below ENT.", "CORRECTED", "Exact"),
        ("sara363.metric.toy-space", "Metric", "Reduced synthetic metric", "Use a 20-bit toy space only to explain scale; it is explicitly not a Bitcoin wallet or key search.", "BOUNDED", "Measured"),
        ("sara363.certificate.public-only", "Certificate", "Public-only derivation certificate", "Return path, parent routing fingerprint, compressed public key, HASH160, script and address while excluding mnemonic-, seed- and private-key-derived commitments.", "ENGINEERING-DERIVED", "Implemented"),
        ("sara363.lineage.audit-record", "Persistence", "Audit lineage record", "Log standards profile, public fixture digest, reason codes and test-vector result, never mnemonic/seed/private keys.", "ENGINEERING-DERIVED", "Specified"),
        ("sara363.handoff.ugts", "Architecture", "Canonical UGTS handoff", "After cryptographic certification, return to support, compatibility, guard, event, transition and lineage.", "RETAIN", "Specified"),
    ]
    return [
        {
            "id": row[0],
            "domain": row[1],
            "name": row[2],
            "formal_definition": row[3],
            "disposition": row[4],
            "validation": row[5],
        }
        for row in raw
    ]


def claims_ledger() -> list[dict[str, Any]]:
    raw = [
        ("SARA-C001", "A BIP39 mnemonic is a human-created sentence or brainwallet.", "REJECT", "BIP39 transports computer-generated entropy and explicitly warns against user-created sentences."),
        ("SARA-C002", "The checksum adds independent secret entropy.", "CORRECT", "The checksum constrains valid encodings and catches some errors; valid mnemonic count remains 2^ENT."),
        ("SARA-C003", "A valid mnemonic checksum proves the owner or wallet balance.", "REJECT", "Checksum validity is syntax/integrity only."),
        ("SARA-C004", "The PBKDF2 step makes weak user passphrases unguessable.", "BOUND", "BIP39 fixes 2048 iterations; passphrase quality remains security-critical."),
        ("SARA-C005", "A public Bitcoin address can be inverted to its private key.", "REJECT", "The address exposes a script commitment and checksum, not spend authority."),
        ("SARA-C006", "Any hash collision can spend a specific P2WPKH output.", "REJECT", "A target preimage matching the witness program and a valid signature path are required; generic collision rhetoric is not sufficient."),
        ("SARA-C007", "A Bech32 checksum authenticates the wallet owner.", "REJECT", "It detects transcription errors; it is not authentication."),
        ("SARA-C008", "An address label on a block explorer proves legal ownership.", "REJECT", "Labels are external metadata and require independent provenance."),
        ("SARA-C009", "A 32-bit BIP32 parent fingerprint is a collision-free identity.", "REJECT", "It is a short identifier and implementations must tolerate collisions."),
        ("SARA-C010", "An extended public key is harmless public information.", "BOUND", "It cannot sign by itself but can reveal address families, balances and privacy-sensitive structure."),
        ("SARA-C011", "Hardened and normal derivation edges are interchangeable.", "REJECT", "Hardened children cannot be derived from an extended public parent."),
        ("SARA-C012", "A Bitcoin address is the same object as a key or wallet.", "REJECT", "Address, script, public key, extended node, seed and mnemonic are distinct typed objects."),
        ("SARA-C013", "The supplied public address authorizes private-key testing because it is public.", "REJECT", "Public visibility does not confer authorization to access or spend funds."),
        ("SARA-C014", "Brute force against a uniformly random 12-word mnemonic is a practical test plan.", "REJECT", "The valid keyspace is 2^128 and the reference metric is astronomically large even at unrealistic rates."),
        ("SARA-C015", "Address-targeted key search belongs in the reference package.", "REJECT", "The package provides decoding and feasibility metrics only, not search or candidate generation."),
        ("SARA-C016", "Mainnet and test networks are equivalent audit environments.", "REJECT", "Training and destructive experiments belong on regtest, signet, testnet or self-owned fixtures."),
        ("SARA-C017", "Seed or mnemonic may be stored in the UGTS lineage log.", "REJECT", "Secrets are transient and prohibited from definitions, traces and certificates."),
        ("SARA-C018", "The same mnemonic words translated into another language preserve the seed.", "REJECT", "BIP39 seed derivation hashes the normalized sentence; translation changes the seed."),
        ("SARA-C019", "One bit can represent the full wallet state.", "REJECT", "Checksums, keys, paths, scripts, policy, uncertainty and lineage remain separate."),
        ("SARA-C020", "Passing public test vectors proves production wallet security.", "REJECT", "It establishes reference conformance only; production security needs hardened libraries, secure entropy and key custody."),
    ]
    return [
        {"id": a, "claim": b, "disposition": c, "technical_note": d}
        for a, b, c, d in raw
    ]


def definition(
    id_: str,
    kind: str,
    domain: str,
    codomain: str,
    phase: int,
    dependencies: list[str],
    parameters: dict[str, Any],
    description: str,
    provenance: list[str],
    status: str,
    invariants: list[str] | None = None,
) -> dict[str, Any]:
    return attach_content_hash(
        {
            "id": id_,
            "kind": kind,
            "domain": domain,
            "codomain": codomain,
            "evaluation_phase": phase,
            "dependencies": dependencies,
            "parameters": parameters,
            "description": description,
            "provenance": provenance,
            "status": status,
            "invariants": invariants or [],
        }
    )


def definitions() -> list[dict[str, Any]]:
    return [
        definition("sara363:profile:v1", "profile", "typed_crypto_input", "public_audit_certificate", 0, [], {"version": VERSION, "secret_serialization": False}, "Seed-address referential profile.", ["BIP39", "BIP32", "BIP84", "BIP173", "BIP350"], "engineering-derived"),
        definition("sara363:op:authorization-gate", "authorization_gate", "audit_scope", "authorization_certificate", 1, ["sara363:profile:v1"], {"allowed": ["bip_test_vector", "public_address_decode", "self_owned_known_seed_derivation", "search_space_estimate"], "forbidden": ["third_party_mainnet_key_search", "mnemonic_enumeration", "private_key_scan", "transaction_signing"]}, "Reject unauthorized secret/funds-access scopes before cryptographic evaluation.", ["package safety boundary"], "engineering-derived"),
        definition("sara363:op:wordlist-commitment", "wordlist_commitment", "wordlist_file", "wordlist_profile", 1, ["sara363:profile:v1"], {"count": 2048, "sha256": WORDLIST_SHA256}, "Bind the English BIP39 wordlist by count, order and hash.", ["BIP39"], "source-derived"),
        definition("sara363:op:entropy-checksum", "checksum_hinge", "entropy_bits", "entropy_plus_checksum", 2, ["sara363:op:wordlist-commitment"], {"ENT": [128,160,192,224,256], "CS": "ENT/32", "hash": "SHA-256"}, "Append the first CS hash bits to ENT.", ["BIP39"], "source-derived", ["ENT+CS divisible by 11"]),
        definition("sara363:op:word-cells", "cell_complex", "entropy_plus_checksum", "ordered_word_cells", 3, ["sara363:op:entropy-checksum", "sara363:op:wordlist-commitment"], {"cell_width": 11, "index_range": [0,2047]}, "Segment the bit string into an ordered path of 11-bit word cells.", ["BIP39", "UGTS topology translation"], "translated"),
        definition("sara363:op:mnemonic-validate", "relation", "mnemonic_sentence", "checksum_status", 4, ["sara363:op:word-cells"], {"normalization": "UTF-8 NFKD"}, "Resolve words to cells and test the checksum hinge.", ["BIP39"], "source-derived"),
        definition("sara363:op:seed-transition", "key_derivation", "mnemonic_sentence x passphrase", "seed512_transient", 5, ["sara363:op:mnemonic-validate", "sara363:op:authorization-gate"], {"function": "PBKDF2-HMAC-SHA512", "iterations": 2048, "salt_prefix": "mnemonic", "bytes": 64, "serialize": False}, "Derive a transient 512-bit seed after scope and checksum validation.", ["BIP39"], "source-derived", ["no secret egress"]),
        definition("sara363:op:bip32-root", "tree_root", "seed512_transient", "extended_private_node", 6, ["sara363:op:seed-transition"], {"hmac_key": "Bitcoin seed", "curve": "secp256k1"}, "Create the BIP32 root node.", ["BIP32"], "source-derived"),
        definition("sara363:op:hd-tree", "key_tree", "extended_node x child_index", "extended_child_node", 7, ["sara363:op:bip32-root"], {"normal_range": [0,2147483647], "hardened_range": [2147483648,4294967295]}, "Apply normal or hardened child-key derivation with explicit edge type.", ["BIP32"], "source-derived"),
        definition("sara363:op:bip84-path", "path_policy", "extended_key_tree", "p2wpkh_leaf", 8, ["sara363:op:hd-tree"], {"path": "m/84'/0'/0'/0/0", "network": "mainnet", "purpose": 84}, "Select the public BIP84 test-vector leaf.", ["BIP84"], "source-derived"),
        definition("sara363:op:public-projection", "public_projection", "p2wpkh_leaf", "compressed_public_key", 9, ["sara363:op:bip84-path"], {"format": "SEC1 compressed", "serialize_private": False}, "Project the private scalar to a public curve point only.", ["BIP32", "SEC1"], "source-derived"),
        definition("sara363:op:hash160", "hash_commitment", "compressed_public_key", "witness_program20", 10, ["sara363:op:public-projection"], {"pipeline": "RIPEMD160(SHA256(pubkey))"}, "Construct the P2WPKH witness program.", ["BIP84", "BIP141"], "source-derived"),
        definition("sara363:op:scriptpubkey", "script_relation", "witness_program20", "script_pubkey", 11, ["sara363:op:hash160"], {"prefix_hex": "0014"}, "Construct witness-v0 P2WPKH scriptPubKey.", ["BIP141", "BIP84"], "source-derived"),
        definition("sara363:op:bech32-address", "address_projection", "witness_program20", "bech32_address", 11, ["sara363:op:hash160"], {"hrp": "bc", "witness_version": 0, "checksum": "Bech32"}, "Encode the public receiving address.", ["BIP173", "BIP84"], "source-derived"),
        definition("sara363:op:public-address-decode", "public_query", "bech32_address", "address_decode_certificate", 3, ["sara363:op:authorization-gate"], {"fixture": TARGET_ADDRESS, "use": "checksum_and_script_decode_only"}, "Decode the supplied public address without key search.", ["user-supplied public fixture", "BIP173", "BIP141"], "bounded"),
        definition("sara363:op:search-space-estimate", "metric", "bit_security x rate", "time_estimate", 3, ["sara363:op:authorization-gate"], {"rates": [1000000, 1000000000000000], "enumeration": False}, "Calculate optimistic expected work without generating candidates.", ["engineering metric"], "engineering-derived"),
        definition("sara363:op:public-certificate", "certificate", "public_derivation x public_decode x metrics", "sara_certificate", 12, ["sara363:op:mnemonic-validate", "sara363:op:bech32-address", "sara363:op:scriptpubkey", "sara363:op:public-address-decode", "sara363:op:search-space-estimate"], {"secret_fields": [], "public_fields": ["fingerprints", "public_key", "script_pubkey", "address", "reason_codes"]}, "Issue a public-only standards-conformance certificate.", ["engineering integration"], "engineering-derived", ["no secret fields"]),
        definition("sara363:op:lineage", "lineage_record", "sara_certificate", "audit_lineage", 13, ["sara363:op:public-certificate"], {"log": ["schema", "source digests", "public fixture", "test results", "reason codes"], "exclude": ["mnemonic", "passphrase", "seed", "private key", "chain code"]}, "Persist public evidence and exclusions only.", ["UGTS lineage"], "engineering-derived"),
        definition("sara363:handoff:ugts", "ugts_handoff", "sara_certificate", "ugts_event_record", 14, ["sara363:op:lineage"], {"sequence": ["support", "compatibility", "guard", "verified_event", "transition", "lineage"]}, "Return control to the canonical UGTS event sequence.", ["UGTS base architecture"], "retained"),
    ]


def example_substrate() -> dict[str, Any]:
    return {
        "$schema": "../spec/ugts_kc_3_6_3_sara.schema.json",
        "schema_version": VERSION,
        "substrate_id": "ugts:kc:3.6.3:sara:seed-address-referential-algebra",
        "metadata": {
            "title": "UGTS-KC 3.6.3 SARA referential example",
            "requester_attribution": {
                "name": "Tom Klootwijk",
                "role": "Principal Creative Technologist",
                "identifier": "NL200678942",
                "date_of_birth": "10-07-1990",
                "status": "requester-supplied-unverified",
            },
            "security_boundary": "Public standards conformance and self-owned validation only. No third-party key search, mnemonic enumeration, signing, broadcast or funds transfer.",
            "base_version": "UGTS-KC 3.6.2 SCLP",
        },
        "definitions": definitions(),
        "instances": [
            {
                "id": "sara363:instance:bip84-public-test-vector",
                "definition_ref": "sara363:profile:v1",
                "literal": {
                    "mnemonic_profile": "BIP39 official public test vector: 128-bit zero entropy",
                    "path": "m/84'/0'/0'/0/0",
                    "expected_address": "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
                    "secret_status": "public test vector",
                },
            },
            {
                "id": "sara363:instance:user-public-address-fixture",
                "definition_ref": "sara363:op:public-address-decode",
                "literal": {
                    "address": TARGET_ADDRESS,
                    "context_label": "user-supplied; not used as ownership proof",
                    "allowed_use": "format/checksum/witness-program/scriptPubKey decode only",
                },
            },
        ],
        "pipelines": [
            {
                "id": "sara363:pipeline:public-certificate",
                "steps": [
                    "sara363:profile:v1",
                    "sara363:op:authorization-gate",
                    "sara363:op:wordlist-commitment",
                    "sara363:op:entropy-checksum",
                    "sara363:op:word-cells",
                    "sara363:op:mnemonic-validate",
                    "sara363:op:seed-transition",
                    "sara363:op:bip32-root",
                    "sara363:op:hd-tree",
                    "sara363:op:bip84-path",
                    "sara363:op:public-projection",
                    "sara363:op:hash160",
                    "sara363:op:scriptpubkey",
                    "sara363:op:bech32-address",
                    "sara363:op:public-address-decode",
                    "sara363:op:search-space-estimate",
                    "sara363:op:public-certificate",
                    "sara363:op:lineage",
                    "sara363:handoff:ugts",
                ],
            }
        ],
    }


def schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/ugts_kc_3_6_3_sara.schema.json",
        "title": "UGTS-KC 3.6.3 SARA substrate",
        "type": "object",
        "required": ["schema_version", "substrate_id", "metadata", "definitions", "instances", "pipelines"],
        "properties": {
            "schema_version": {"const": VERSION},
            "substrate_id": {"type": "string", "minLength": 1},
            "metadata": {"type": "object"},
            "definitions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "kind", "domain", "codomain", "evaluation_phase", "dependencies", "content_hash"],
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"type": "string"},
                        "domain": {"type": "string"},
                        "codomain": {"type": "string"},
                        "evaluation_phase": {"type": "integer", "minimum": 0},
                        "dependencies": {"type": "array", "items": {"type": "string"}},
                        "content_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    },
                    "additionalProperties": True,
                },
            },
            "instances": {"type": "array"},
            "pipelines": {"type": "array"},
        },
        "additionalProperties": True,
    }


def source_register() -> dict[str, Any]:
    return {
        "version": VERSION,
        "retrieved": "2026-08-18",
        "sources": [
            {"id": "STD-BIP39", "title": "BIP 39: Mnemonic code for generating deterministic keys", "url": "https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki", "role": "entropy/checksum/word cells/PBKDF2", "status": "primary standard"},
            {"id": "STD-BIP32", "title": "BIP 32: Hierarchical Deterministic Wallets", "url": "https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki", "role": "extended-key tree and child derivation", "status": "primary standard"},
            {"id": "STD-BIP44", "title": "BIP 44: Multi-account hierarchy", "url": "https://github.com/bitcoin/bips/blob/master/bip-0044.mediawiki", "role": "path-level semantics", "status": "primary standard"},
            {"id": "STD-BIP84", "title": "BIP 84: Derivation scheme for P2WPKH accounts", "url": "https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki", "role": "m/84' path and public test vectors", "status": "primary standard"},
            {"id": "STD-BIP141", "title": "BIP 141: Segregated Witness", "url": "https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki", "role": "witness program and P2WPKH script relation", "status": "primary standard"},
            {"id": "STD-BIP173", "title": "BIP 173: Bech32 native witness addresses", "url": "https://github.com/bitcoin/bips/blob/master/bip-0173.mediawiki", "role": "v0 address encoding/checksum", "status": "primary standard"},
            {"id": "STD-BIP350", "title": "BIP 350: Bech32m", "url": "https://github.com/bitcoin/bips/blob/master/bip-0350.mediawiki", "role": "v1-v16 address checksum", "status": "primary standard"},
            {"id": "BASE-SCLP", "title": "UGTS-KC 3.6.2 SCLP", "role": "referential geometry/topology and canonical UGTS handoff", "status": "inherited package"},
            {"id": "FIXTURE-USER-ADDRESS", "title": "User-supplied public Bech32 address", "value": TARGET_ADDRESS, "role": "public checksum and script decode only", "status": "ownership label not validated"},
        ],
    }


def write_formal_definition() -> None:
    text = f"""# UGTS-KC 3.6.3 SARA formal definition\n\n## Seed-Address Referential Algebra\n\nVersion 3.6.3 maps the public deterministic wallet pipeline into a typed referential substrate while imposing a non-negotiable authorization and secret-handling boundary. It does not implement third-party wallet brute force, candidate enumeration, transaction signing, broadcasting or funds transfer.\n\n### Core state\n\nThe abstract cryptographic state is\n\n```text\nq_crypto = (profile, ENT, CS, word_cells, mnemonic, seed_transient,\n            hd_node_transient, derivation_path, public_key, witness_program,\n            script_pubkey, address, authorization, lineage)\n```\n\n`word_cells`, the mnemonic, passphrase, `seed_transient`, private scalars and chain codes are never serialized into the public certificate. Secret-equivalent cell indices and mnemonic-, entropy- or seed-derived fingerprints are excluded as well.\n\n### BIP39 cell map\n\n```text\nCS = ENT / 32\nMS = (ENT + CS) / 11\nB = ENT || prefix_CS(SHA256(ENT))\nword_cell_i = B[11i : 11(i+1)] in [0,2047]\n```\n\nThe ordered words form a one-dimensional labeled cell complex. The checksum is a guard relation, not an ownership proof.\n\n### Seed transition\n\n```text\nseed = PBKDF2-HMAC-SHA512(\n    password=NFKD(mnemonic),\n    salt=NFKD('mnemonic' || passphrase),\n    iterations=2048,\n    bytes=64\n)\n```\n\n### HD tree\n\nBIP32 nodes carry key material, chain code, depth, parent fingerprint and child number. Normal edges use indices below `2^31`; hardened edges use indices at or above `2^31` and cannot be derived from an extended public parent. The BIP84 public test path is `m/84'/0'/0'/0/0`.\n\n### Address projection\n\n```text\npubkey = compressed(point(private_scalar))\nprogram = RIPEMD160(SHA256(pubkey))\nscriptPubKey = 0x0014 || program\naddress = Bech32(hrp='bc', witness_version=0, program)\n```\n\nThe user-supplied public fixture decodes to witness version 0, a 20-byte witness program and P2WPKH scriptPubKey. This is a public structural observation; it is not a route to a private key.\n\n### Authorization guard\n\nPermitted scopes are public test vectors, self-owned known-seed validation, public address decoding, watch-only checks, regtest/signet/testnet experiments and search-space estimation. Forbidden scopes include third-party mainnet key search, mnemonic enumeration, passphrase spraying, private-key scanning, transaction signing, broadcast and funds transfer.\n\n### Search metrics\n\nThe package computes expected work only; it does not enumerate. For a uniform `b`-bit space at rate `R`, expected work is `2^(b-1)` trials and expected time is `2^(b-1)/R`. A 12-word BIP39 sentence carries 128 bits of entropy; its checksum makes one in sixteen arbitrary 12-word index sequences syntactically valid but does not reduce the valid space below `2^128`.\n\n### UGTS handoff\n\nAfter public cryptographic certification, authority returns to:\n\n```text\nsupport -> compatibility -> guard -> verified event -> transition -> lineage\n```\n"""
    (ROOT / "spec" / "SARA_3_6_3_FORMAL_DEFINITION.md").write_text(text, encoding="utf-8")


def main() -> None:
    for folder in ("spec", "data", "examples", "sources", "report", "report/figures"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)

    operators = operator_catalog()
    claims = claims_ledger()
    write_json(ROOT / "spec" / "sara_3_6_3_delta_operator_catalog.json", operators)
    write_csv(ROOT / "spec" / "sara_3_6_3_delta_operator_catalog.csv", operators)
    write_json(ROOT / "spec" / "sara_3_6_3_claims_ledger.json", claims)
    write_csv(ROOT / "spec" / "sara_3_6_3_claims_ledger.csv", claims)
    write_json(ROOT / "spec" / "ugts_kc_3_6_3_sara.schema.json", schema())
    write_formal_definition()

    example = example_substrate()
    write_json(ROOT / "examples" / "ugts_kc_3_6_3_sara_example.json", example)
    # Internal referential validation.
    Substrate.from_dict(example)

    certificate = build_reference_sara363_certificate(ROOT / "data" / "bip39_english.txt")
    write_json(ROOT / "data" / "sara363_reference_certificate.json", asdict(certificate))
    runtime_output = SARARuntime(ROOT / "data" / "bip39_english.txt").run_reference()
    write_json(ROOT / "examples" / "demo_sara363_output.json", runtime_output["certificate"])
    write_json(ROOT / "examples" / "demo_sara363_trace.json", runtime_output["trace"])

    decoded = decode_segwit_address(TARGET_ADDRESS)
    public_fixture = asdict(decoded)
    public_fixture["context_label"] = "user-supplied; ownership not established by package"
    public_fixture["allowed_use"] = "public format/checksum/witness-program/scriptPubKey decode only"
    write_json(ROOT / "data" / "sara363_public_address_fixture.json", public_fixture)

    metrics = [
        asdict(estimate_uniform_search(128, 1e15)),
        asdict(estimate_uniform_search(160, 1e15)),
        asdict(estimate_uniform_search(256, 1e15)),
        asdict(estimate_uniform_search(20, 1e6)),
    ]
    write_json(ROOT / "data" / "sara363_search_space_metrics.json", metrics)
    write_csv(ROOT / "data" / "sara363_search_space_metrics.csv", metrics)
    write_json(ROOT / "sources" / "source_register_3_6_3_sara.json", source_register())

    summary = {
        "version": VERSION,
        "profile": PROFILE_ID,
        "operator_count": len(operators),
        "definition_count": len(example["definitions"]),
        "claims_count": len(claims),
        "reference_certificate_valid": certificate.valid,
        "wordlist_sha256": WORDLIST_SHA256,
        "public_fixture": public_fixture,
    }
    write_json(ROOT / "validation_report_3_6_3.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
