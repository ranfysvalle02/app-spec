# Data Model Specification

> Auto-generated from `appspec.json` — Veterinary Clinic (vet-clinic)

## Overview

**Application:** Veterinary Clinic
**Entities:** 3
**Schema Version:** 1.0

A comprehensive application for managing pet owners, their pets (patients), and all associated appointments within a veterinary clinic.

---

## Owner

**Collection:** `owners`

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the owner. |
| `first_name` | string | Yes | The first name of the pet owner. |
| `last_name` | string | Yes | The last name of the pet owner. |
| `email` | string | Yes | The email address of the pet owner, used for communication. |
| `phone_number` | string | Yes | The primary phone number of the pet owner. |
| `address` | string | Yes | The physical address of the pet owner. |
| `created_at` | datetime | Yes | Timestamp when the owner record was created. |

**Filterable:** first_name, last_name, email
**Sortable:** first_name, last_name, email, created_at




---

## Patient

**Collection:** `patients`

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the patient (pet). |
| `name` | string | Yes | The name of the pet. |
| `species` | string | Yes | The species of the pet (e.g., Dog, Cat, Bird). |
| `breed` | string | Yes | The breed of the pet. |
| `date_of_birth` | datetime | Yes | The birth date of the pet. |
| `owner_id` | reference → `owners` | Yes | Reference to the owner of this pet. |
| `created_at` | datetime | Yes | Timestamp when the patient record was created. |

**Filterable:** name, species, breed, owner_id
**Sortable:** name, species, breed, date_of_birth, owner_id, created_at




---

## Appointment

**Collection:** `appointments`

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the appointment. |
| `patient_id` | reference → `patients` | Yes | Reference to the patient (pet) for this appointment. |
| `owner_id` | reference → `owners` | Yes | Reference to the owner associated with this appointment. |
| `appointment_date` | datetime | Yes | The date and time of the appointment. |
| `reason` | string | Yes | The reason for the appointment (e.g., check-up, vaccination, emergency). |
| `status` | enum (scheduled, completed, cancelled, no_show) | Yes | The current status of the appointment. |
| `notes` | text | Yes | Any additional notes or observations for the appointment. |
| `created_at` | datetime | Yes | Timestamp when the appointment record was created. |

**Filterable:** patient_id, owner_id, appointment_date, reason, status
**Sortable:** patient_id, owner_id, appointment_date, status, created_at




---

