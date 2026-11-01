import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { Observable, map } from 'rxjs';

export type Sensitivity = 'broad' | 'balanced' | 'strict';
export type SearchStatus = 'awaiting_reference_selection' | 'uploading' | 'queued' | 'scanning' | 'reviewing' | 'saved' | 'failed' | 'cancelled';

export interface SearchInfo {
  id: string;
  status: SearchStatus;
  sensitivity: Sensitivity;
  threshold: number;
  expectedFiles: number;
  expectedBytes: number;
  uploadedFiles: number;
  uploadedBytes: number;
  processedFiles: number;
  matchedFiles: number;
  failedFiles: number;
  collectionName: string | null;
  errorMessage: string | null;
  createdAt?: string;
  completedAt?: string | null;
}

export interface ReferenceFace {
  id: string;
  bbox: Record<string, number>;
  previewUrl: string;
}

export interface MatchItem {
  id: string;
  assetId: string;
  sourceRelativePath: string;
  similarity: number;
  bbox: Record<string, any>;
  emotion: string;
  decision: 'accepted' | 'rejected' | 'undecided';
  thumbnailUrl: string;
  imageUrl: string;
}

interface SearchCreationResponse { search: SearchInfo; referenceFaces: ReferenceFace[]; }
interface SearchResponse { search: SearchInfo; }
export interface MatchResponse { items: MatchItem[]; emotionCounts?: Record<string, number>; nextCursor: string | null; }
interface SearchListResponse { items: SearchInfo[]; }

@Injectable({ providedIn: 'root' })
export class ApiService {
  readonly apiBaseUrl = signal('http://127.0.0.1:8000/api/v1');

  constructor(private readonly http: HttpClient) {}

  createSearch(reference: File, expectedFiles: number, expectedBytes: number, sensitivity: Sensitivity): Observable<SearchCreationResponse> {
    const body = new FormData();
    body.append('reference', reference);
    body.append('expected_files', String(expectedFiles));
    body.append('expected_bytes', String(expectedBytes));
    body.append('sensitivity', sensitivity);
    return this.http.post<SearchCreationResponse>(`${this.apiBaseUrl()}/searches`, body);
  }

  selectReference(searchId: string, referenceFaceId: string): Observable<SearchResponse> {
    return this.http.post<SearchResponse>(`${this.apiBaseUrl()}/searches/${searchId}/reference-face`, { reference_face_id: referenceFaceId });
  }

  uploadBatch(searchId: string, clientBatchId: string, items: File[]): Observable<number> {
    const body = new FormData();
    body.append('client_batch_id', clientBatchId);
    body.append('manifest', JSON.stringify(items.map(file => ({ relativePath: file.webkitRelativePath || file.name }))));
    for (const file of items) body.append('files', file, file.name);
    return this.http.post(`${this.apiBaseUrl()}/searches/${searchId}/batches`, body, { observe: 'events', reportProgress: true }).pipe(
      map((event: HttpEvent<unknown>) => {
        if (event.type === HttpEventType.UploadProgress && event.total) return Math.round(event.loaded / event.total * 100);
        return event.type === HttpEventType.Response ? 100 : 0;
      })
    );
  }

  finalize(searchId: string): Observable<SearchResponse> {
    return this.http.post<SearchResponse>(`${this.apiBaseUrl()}/searches/${searchId}/finalize`, {});
  }

  getSearch(searchId: string): Observable<SearchResponse> {
    return this.http.get<SearchResponse>(`${this.apiBaseUrl()}/searches/${searchId}`);
  }

  getMatches(searchId: string, emotion?: string, decision?: string): Observable<MatchResponse> {
    const params: string[] = [];
    if (emotion && emotion !== 'all') params.push(`emotion=${encodeURIComponent(emotion)}`);
    if (decision && decision !== 'all') params.push(`decision=${encodeURIComponent(decision)}`);
    const query = params.length ? `?${params.join('&')}` : '';
    return this.http.get<MatchResponse>(`${this.apiBaseUrl()}/searches/${searchId}/matches${query}`);
  }

  setDecision(matchId: string, decision: MatchItem['decision']): Observable<{ id: string; decision: MatchItem['decision'] }> {
    return this.http.patch<{ id: string; decision: MatchItem['decision'] }>(`${this.apiBaseUrl()}/matches/${matchId}`, { decision });
  }

  saveCollection(searchId: string, name: string): Observable<SearchResponse> {
    return this.http.post<SearchResponse>(`${this.apiBaseUrl()}/searches/${searchId}/save`, { name });
  }

  getCollections(): Observable<SearchListResponse> {
    return this.http.get<SearchListResponse>(`${this.apiBaseUrl()}/collections`);
  }

  getActivity(): Observable<SearchListResponse> {
    return this.http.get<SearchListResponse>(`${this.apiBaseUrl()}/activity`);
  }

  deleteSearch(searchId: string): Observable<void> {
    return this.http.delete<void>(`${this.apiBaseUrl()}/searches/${searchId}`);
  }

  mediaUrl(relativeUrl: string): string {
    return `http://127.0.0.1:8000${relativeUrl}`;
  }
}
