export type ReadyResponse = {
  status: "ready" | "degraded";
  application_name: string;
  application_version: string;
  api: {
    status: string;
  };
  database: {
    status: string;
    detail: string | null;
  };
  migrations: {
    status: string;
    revision: string | null;
    detail: string | null;
  };
  checked_at: string;
};

export type VideoListItem = {
  id: string;
  file_path: string;
  title: string;
  file_size: number;
  status: string;
  added_at: string;
  last_seen_at: string;
  duration_seconds?: number | null;
  thumbnail_url?: string | null;
  resume_position_seconds?: number | null;
  completed?: boolean | null;
  recommendation_reason?: string | null;
};

export type VideoListResponse = {
  items: VideoListItem[];
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
};

export type VideoRead = {
  id: string;
  file_path: string;
  title: string;
  title_override: string | null;
  file_size: number;
  file_mtime: string;
  fingerprint: string | null;
  status: string;
  added_at: string;
  last_seen_at: string;
  unavailable_since: string | null;
  watch_count: number;
  last_watched_at: string | null;
  created_at: string;
  updated_at: string;
  resume_position_seconds: number | null;
};

export type RankedFeedPage = {
  items: VideoListItem[];
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
};

export type FeedResponse = {
  continue_watching: VideoListItem[];
  recommendations: RankedFeedPage;
};

export type Tag = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
};
