# API Specification

> Auto-generated from `appspec.json` — Veterinary Clinic (vet-clinic)

## Overview

**Application:** Veterinary Clinic
**Endpoints:** 15
**Authentication:** jwt
**Roles:** admin, vet, receptionist


---

## Authentication

| Property | Value |
|----------|-------|
| Strategy | jwt |
| Roles | admin, vet, receptionist |
| Default Role | None |

## Endpoints

### Owner

| Method | Path | Operation | Auth | Description |
|--------|------|-----------|------|-------------|
| `GET` | `/owners` | list | No | Retrieve a list of all pet owners. |
| `GET` | `/owners/{id}` | get | No | Retrieve a specific pet owner by ID. |
| `POST` | `/owners` | create | No | Create a new pet owner record. |
| `PUT` | `/owners/{id}` | update | No | Update an existing pet owner record by ID. |
| `DELETE` | `/owners/{id}` | delete | No | Delete a pet owner record by ID. |

### Patient

| Method | Path | Operation | Auth | Description |
|--------|------|-----------|------|-------------|
| `GET` | `/patients` | list | No | Retrieve a list of all patients (pets). |
| `GET` | `/patients/{id}` | get | No | Retrieve a specific patient (pet) by ID. |
| `POST` | `/patients` | create | No | Create a new patient (pet) record. |
| `PUT` | `/patients/{id}` | update | No | Update an existing patient (pet) record by ID. |
| `DELETE` | `/patients/{id}` | delete | No | Delete a patient (pet) record by ID. |

### Appointment

| Method | Path | Operation | Auth | Description |
|--------|------|-----------|------|-------------|
| `GET` | `/appointments` | list | No | Retrieve a list of all appointments. |
| `GET` | `/appointments/{id}` | get | No | Retrieve a specific appointment by ID. |
| `POST` | `/appointments` | create | No | Create a new appointment record. |
| `PUT` | `/appointments/{id}` | update | No | Update an existing appointment record by ID. |
| `DELETE` | `/appointments/{id}` | delete | No | Delete an appointment record by ID. |


