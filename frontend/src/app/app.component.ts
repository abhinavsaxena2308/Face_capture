import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnDestroy, ViewChild, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService, MatchItem, ReferenceFace, SearchInfo, Sensitivity } from './api.service';

type AppView = 'setup' | 'reference-choice' | 'uploading' | 'progress' | 'results';
type Section = 'Search' | 'Collections' | 'Activity';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnDestroy {
  @ViewChild('referenceInput') referenceInput?: ElementRef<HTMLInputElement>;
  @ViewChild('folderInput') folderInput?: ElementRef<HTMLInputElement>;

  private readonly api = inject(ApiService);
  readonly referenceFile = signal<File | null>(null);
  readonly referenceUrl = signal<string | null>(null);
  readonly collectionFiles = signal<File[]>([]);
  readonly photoCount = signal(0);
  readonly totalBytes = signal(0);
  readonly sensitivity = signal<Sensitivity>('balanced');
  readonly notice = signal('');
  readonly activeSection = signal<Section>('Search');
  readonly view = signal<AppView>('setup');
  readonly isWorking = signal(false);
  readonly uploadPercent = signal(0);
  readonly search = signal<SearchInfo | null>(null);
  readonly referenceCandidates = signal<ReferenceFace[]>([]);
  readonly matches = signal<MatchItem[]>([]);
  readonly records = signal<SearchInfo[]>([]);
  readonly recordsLoading = signal(false);
  readonly workspaceMenuOpen = signal(false);
  readonly profileMenuOpen = signal(false);
  readonly helpOpen = signal(false);
  private objectUrl: string | null = null;
  private pollTimer: number | null = null;

  get sizeLabel(): string {
    const bytes = this.totalBytes();
    if (bytes === 0) return 'No images selected yet';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB selected`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB selected`;
  }

  get selectedSensitivityLabel(): string {
    return { broad: 'More results', balanced: 'Balanced', strict: 'Higher confidence' }[this.sensitivity()];
  }

  get progressPercent(): number {
    const current = this.search();
    if (!current?.expectedFiles) return 0;
    return Math.min(100, Math.round(current.processedFiles / current.expectedFiles * 100));
  }

  openReferencePicker(): void { this.referenceInput?.nativeElement.click(); }
  openFolderPicker(): void { this.folderInput?.nativeElement.click(); }

  onReferenceChange(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (file) this.setReference(file);
  }

  onReferenceDrop(event: DragEvent): void {
    const file = event.dataTransfer?.files?.[0];
    if (file) this.setReference(file);
  }

  private setReference(file: File): void {
    if (!file.type.startsWith('image/') && !/\.(heic|heif)$/i.test(file.name)) {
      this.notice.set('Choose a JPG, PNG, WEBP, HEIC, or HEIF image.');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      this.notice.set('The reference image must be 20 MB or smaller.');
      return;
    }
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = URL.createObjectURL(file);
    this.referenceFile.set(file);
    this.referenceUrl.set(this.objectUrl);
    this.notice.set('');
  }

  onFolderChange(event: Event): void {
    this.setCollection(Array.from((event.target as HTMLInputElement).files ?? []));
  }

  onCollectionDrop(event: DragEvent): void {
    this.setCollection(Array.from(event.dataTransfer?.files ?? []));
  }

  private setCollection(selectedFiles: File[]): void {
    const files = selectedFiles.filter(file => file.type.startsWith('image/') || /\.(heic|heif)$/i.test(file.name));
    if (files.length > 25_000) {
      this.notice.set('Choose 25,000 images or fewer for one search.');
      return;
    }
    this.collectionFiles.set(files);
    this.photoCount.set(files.length);
    this.totalBytes.set(files.reduce((total, file) => total + file.size, 0));
    this.notice.set(files.length ? '' : 'This folder did not contain supported image files.');
  }

  setSensitivity(value: Sensitivity): void { this.sensitivity.set(value); }

  async createSearch(): Promise<void> {
    const reference = this.referenceFile();
    const files = this.collectionFiles();
    if (!reference || files.length === 0 || this.isWorking()) return;
    this.isWorking.set(true);
    this.notice.set('Checking your reference photo locally…');
    try {
      const response = await firstValueFrom(this.api.createSearch(reference, files.length, this.totalBytes(), this.sensitivity()));
      this.search.set(response.search);
      this.referenceCandidates.set(response.referenceFaces);
      if (response.referenceFaces.length === 1) {
        await this.selectReference(response.referenceFaces[0]);
      } else {
        this.view.set('reference-choice');
        this.notice.set('Choose the face you want to find in your photo collection.');
        this.isWorking.set(false);
      }
    } catch (error) {
      this.showError(error, 'Could not prepare the face search.');
      this.isWorking.set(false);
    }
  }

  async selectReference(candidate: ReferenceFace): Promise<void> {
    const current = this.search();
    if (!current) return;
    this.isWorking.set(true);
    try {
      const selected = await firstValueFrom(this.api.selectReference(current.id, candidate.id));
      this.search.set(selected.search);
      await this.uploadCollection(selected.search.id);
    } catch (error) {
      this.showError(error, 'Could not select the reference face.');
      this.isWorking.set(false);
    }
  }

  private async uploadCollection(searchId: string): Promise<void> {
    const files = this.collectionFiles();
    this.view.set('uploading');
    this.notice.set('Copying selected images to the local scanner…');
    const batchSize = 25;
    let uploaded = 0;
    try {
      for (let start = 0; start < files.length; start += batchSize) {
        const batch = files.slice(start, start + batchSize);
        await new Promise<void>((resolve, reject) => this.api.uploadBatch(searchId, crypto.randomUUID(), batch).subscribe({
          next: progress => this.uploadPercent.set(Math.round((uploaded + batch.length * progress / 100) / files.length * 100)),
          error: reject,
          complete: resolve
        }));
        uploaded += batch.length;
        this.uploadPercent.set(Math.round(uploaded / files.length * 100));
      }
      const finalized = await firstValueFrom(this.api.finalize(searchId));
      this.search.set(finalized.search);
      this.view.set('progress');
      this.notice.set('Scanning is running locally. You can keep this tab open to review progress.');
      this.isWorking.set(false);
      void this.pollSearch();
      this.startPolling();
    } catch (error) {
      this.showError(error, 'Image upload stopped before the scan could start.');
      this.isWorking.set(false);
      this.view.set('setup');
    }
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollTimer = window.setInterval(() => void this.pollSearch(), 2000);
  }

  private async pollSearch(): Promise<void> {
    const current = this.search();
    if (!current) return;
    try {
      const response = await firstValueFrom(this.api.getSearch(current.id));
      this.search.set(response.search);
      if (response.search.status === 'reviewing' || response.search.status === 'saved') {
        this.stopPolling();
        const matches = await firstValueFrom(this.api.getMatches(current.id));
        this.matches.set(matches.items);
        this.view.set('results');
        this.notice.set(`${response.search.matchedFiles} possible matches are ready for review.`);
      } else if (response.search.status === 'failed') {
        this.stopPolling();
        this.view.set('setup');
        this.notice.set(response.search.errorMessage || 'The scan did not complete.');
      }
    } catch {
      this.notice.set('The local API is unavailable. Start the backend and worker, then this screen will retry.');
    }
  }

  async setMatchDecision(match: MatchItem, decision: MatchItem['decision']): Promise<void> {
    try {
      await firstValueFrom(this.api.setDecision(match.id, decision));
      this.matches.update(items => items.map(item => item.id === match.id ? { ...item, decision } : item));
    } catch (error) {
      this.showError(error, 'Could not update this match.');
    }
  }

  async saveCollection(): Promise<void> {
    const current = this.search();
    if (!current) return;
    try {
      const name = `Face matches ${new Date().toLocaleDateString()}`;
      const response = await firstValueFrom(this.api.saveCollection(current.id, name));
      this.search.set(response.search);
      this.notice.set(`Saved as “${name}”.`);
    } catch (error) {
      this.showError(error, 'Could not save the collection.');
    }
  }

  async navigate(section: Section): Promise<void> {
    this.activeSection.set(section);
    this.workspaceMenuOpen.set(false);
    this.profileMenuOpen.set(false);
    this.helpOpen.set(false);
    if (section === 'Search') {
      this.view.set('setup');
      this.notice.set('');
      return;
    }

    this.recordsLoading.set(true);
    this.notice.set('');
    try {
      const response = section === 'Collections'
        ? await firstValueFrom(this.api.getCollections())
        : await firstValueFrom(this.api.getActivity());
      this.records.set(response.items);
    } catch (error) {
      this.showError(error, `Could not load ${section.toLowerCase()}.`);
    } finally {
      this.recordsLoading.set(false);
    }
  }

  async openRecord(record: SearchInfo): Promise<void> {
    try {
      const response = await firstValueFrom(this.api.getSearch(record.id));
      this.search.set(response.search);
      this.activeSection.set('Search');
      this.notice.set('');
      if (response.search.status === 'reviewing' || response.search.status === 'saved') {
        const matches = await firstValueFrom(this.api.getMatches(record.id));
        this.matches.set(matches.items);
        this.view.set('results');
      } else if (response.search.status === 'queued' || response.search.status === 'scanning') {
        this.view.set('progress');
        this.startPolling();
        void this.pollSearch();
      } else {
        this.view.set('setup');
        this.notice.set(response.search.errorMessage || `This search is ${response.search.status.replaceAll('_', ' ')}.`);
      }
    } catch (error) {
      this.showError(error, 'Could not open this search.');
    }
  }

  async deleteRecord(event: Event, record: SearchInfo): Promise<void> {
    event.stopPropagation();
    const name = record.collectionName || 'this search';
    if (!window.confirm(`Delete ${name} and its retained matched files?`)) return;
    try {
      await firstValueFrom(this.api.deleteSearch(record.id));
      await this.navigate(this.activeSection());
      this.notice.set('Search and its retained files were deleted.');
    } catch (error) {
      this.showError(error, 'Could not delete this search.');
    }
  }

  toggleWorkspaceMenu(): void {
    this.workspaceMenuOpen.update(open => !open);
    this.profileMenuOpen.set(false);
    this.helpOpen.set(false);
  }

  toggleProfileMenu(): void {
    this.profileMenuOpen.update(open => !open);
    this.workspaceMenuOpen.set(false);
    this.helpOpen.set(false);
  }

  toggleHelp(): void {
    this.helpOpen.update(open => !open);
    this.workspaceMenuOpen.set(false);
    this.profileMenuOpen.set(false);
  }

  recordDate(record: SearchInfo): string {
    return record.completedAt || record.createdAt || '';
  }

  clearReference(): void {
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
    this.objectUrl = null;
    this.referenceFile.set(null);
    this.referenceUrl.set(null);
    if (this.referenceInput) this.referenceInput.nativeElement.value = '';
  }

  clearFolder(): void {
    this.collectionFiles.set([]);
    this.photoCount.set(0);
    this.totalBytes.set(0);
    if (this.folderInput) this.folderInput.nativeElement.value = '';
  }

  imageUrl(relativeUrl: string): string { return this.api.mediaUrl(relativeUrl); }

  private stopPolling(): void {
    if (this.pollTimer !== null) window.clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  private showError(error: unknown, fallback: string): void {
    const apiError = error as { error?: { detail?: string } };
    this.notice.set(apiError.error?.detail || fallback);
  }

  ngOnDestroy(): void {
    this.stopPolling();
    if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
  }
}
