export interface Organization {
  id: string
  name: string
  alternate_name: string | null
  description: string
  email: string | null
  website: string | null
  legal_status: string | null
  year_incorporated: number | null
  logo: string | null
  uri: string | null
  parent_organization_id: string | null
  created_at: string
  updated_at: string
}

export type OrganizationIn = Omit<Organization, 'id' | 'created_at' | 'updated_at'>

export interface Location {
  id: string
  organization_id: string | null
  name: string | null
  alternate_name: string | null
  description: string | null
  address: string | null
  latitude: string | null
  longitude: string | null
  created_at: string
  updated_at: string
}

export type LocationIn = Omit<Location, 'id' | 'created_at' | 'updated_at'>

export interface Service {
  id: string
  organization_id: string
  name: string
  alternate_name: string | null
  description: string | null
  url: string | null
  email: string | null
  status: 'active' | 'inactive' | 'defunct' | 'temporarily closed'
  interpretation_services: string | null
  application_process: string | null
  fees_description: string | null
  eligibility_description: string | null
  minimum_age: string | null
  maximum_age: string | null
  assured_date: string | null
  alert: string | null
  last_modified: string | null
  created_at: string
  updated_at: string
}

export type ServiceIn = Omit<Service, 'id' | 'created_at' | 'updated_at'>

export interface ServiceAtLocation {
  id: string
  service_id: string
  location_id: string
  description: string | null
  created_at: string
  updated_at: string
}

export type ServiceAtLocationIn = Omit<ServiceAtLocation, 'id' | 'created_at' | 'updated_at'>

export type LocationServiceIn = Omit<ServiceIn, 'organization_id'>

export type LocationServiceOut = Service & {
  service_at_location_id: string
}


// ── Interview sessions, documents, chat ─────────────────

export interface InterviewSession {
  id: string
  status: 'active' | 'ended' | 'expired'
  created_at: string
  expires_at: string
  postal_code: string | null
  origin_display_name: string | null
}

export interface GeocodeSuggestion {
  lat: number
  lng: number
  display_name: string
  postcode: string | null
  city: string | null
}

export interface SessionLocation {
  postal_code: string | null
  origin_lat: string | null
  origin_lng: string | null
  origin_display_name: string | null
}

export interface DocumentMeta {
  id: string
  filename: string
  mime_type: string | null
  size_bytes: number
  route: string | null
  quality_status: string
  page_count: number
  block_count: number
  token_estimate: number
  status: 'ready' | 'skipped_too_large' | 'quarantine' | 'failed'
  skip_reason: string | null
  created_at: string
}

export interface SkippedDocument {
  id: string
  filename: string
  reason: string
  token_estimate: number | null
  remaining_budget: number | null
}

export interface ContextPrompt {
  system_prompt: string
  included: DocumentMeta[]
  skipped: SkippedDocument[]
  total_tokens: number
  budget_tokens: number
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ServiceCard {
  index: number
  service: {
    id: string
    name: string
    category: string
    status: string
    distance_km: number
    location_name: string | null
    address: string | null
    description: string | null
    eligibility_description: string | null
    application_process: string | null
    fees_description: string | null
    email: string | null
    url: string | null
  }
}

export type ChatItem =
  | { kind: 'message'; role: 'user' | 'assistant'; content: string }
  | { kind: 'card'; card: ServiceCard }