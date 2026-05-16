(() => {
  const site = window.WEBHOST_SITE;
  const fileInput = document.getElementById("zip-file");
  const dropZone = document.getElementById("drop-zone");
  const reloadButton = document.getElementById("reload-button");
  const deleteButton = document.getElementById("delete-button");
  const publishEmptyButton = document.getElementById("publish-empty-button");
  const prodEmptyBadge = document.getElementById("prod-empty-badge");
  const uploadStatus = document.getElementById("upload-status");
  const archiveStatus = document.getElementById("archive-status");
  const archiveStatusProgress = document.getElementById("archive-status-progress");
  const archiveStatusStop = document.getElementById("archive-status-stop");
  const archivesList = document.getElementById("archives-list");
  const archiveLoadingOverlay = document.getElementById("archive-loading-overlay");
  const toast = document.getElementById("toast");
  let archives = [];
  let selected = new Set();
  let preparedObjectPath = "";
  let isBusy = false;
  let pageDragDepth = 0;
  let processingArchives = [];
  let archiveProcessingStatuses = new Map();
  let archivePollTimer = null;
  let operationStreamController = null;
  let operationStreamId = "";
  let lastAppliedOperationKey = "";
  const lang = window.WEBHOST_LANG === "en" ? "en" : "ja";
  const messages = {
    ja: {
      busy: "処理中です。",
      failed: "処理に失敗しました。",
      progressReadFailed: "進捗を読み取れませんでした。",
      completionUnknown: "処理の完了を確認できませんでした。",
      done: "完了しました。",
      downloadZip: "履歴ZIPをダウンロード",
      noNote: "メモなし",
      saving: "保存中",
      save: "保存",
      cancel: "キャンセル",
      noteSaved: "メモを保存しました。",
      noArchives: "履歴はありません。",
      cannotSelectProcessing: "処理中の履歴は選択できません",
      cannotDeletePublished: "公開中の履歴は削除できません",
      selectForDelete: "削除対象に選択",
      published: "公開中",
      openProduction: "本番サイトを開く",
      staging: "確認中",
      openStaging: "確認サイトを開く",
      failedLabel: "失敗",
      processingLabel: "処理中",
      prepareStaging: "確認サイトを用意する",
      publish: "公開する",
      loadingArchives: "履歴を読み込んでいます...",
      archivesCount: "履歴 {count}/{limit} 件",
      chooseZip: "ZIPファイルを選択してください。",
      signingUpload: "アップロードURLを取得しています...",
      uploadingZip: "ZIPをアップロードしています...",
      uploadFailed: "ZIPアップロードに失敗しました。",
      addingArchive: "履歴に追加しています...",
      archiveAdded: "履歴に追加しました。{count}件",
      prepareStarting: "確認サイトの準備を開始しています。",
      prepareFailed: "確認サイトの準備に失敗しました。",
      preparingStaging: "確認サイトを用意しています。",
      preparedStaging: "確認サイトを用意しました。",
      preparingBeforePublish: "公開前に確認サイトを用意しています。",
      confirmPublish: "{siteName} にこの履歴を公開します。よろしいですか？",
      publishStarting: "公開を開始しています。",
      publishFailed: "公開に失敗しました。",
      publishing: "公開しています。",
      publishedToast: "公開しました。送信{copied}件 / 削除{deleted}件",
      confirmEmpty: "{siteName} の本番を空にします。履歴から復旧できます。よろしいですか？",
      emptyingProduction: "本番を空にしています...",
      emptyFailed: "本番を空にできませんでした。",
      emptiedProduction: "本番を空にしました。",
      confirmDelete: "{count}件の履歴を削除します。よろしいですか？",
      deletingArchives: "履歴を削除しています...",
      deletedArchives: "履歴を削除しました。",
      stop: "ストップ",
      stopping: "停止しています。",
    },
    en: {
      busy: "Processing.",
      failed: "Operation failed.",
      progressReadFailed: "Could not read progress.",
      completionUnknown: "Could not confirm completion.",
      done: "Done.",
      downloadZip: "Download archive ZIP",
      noNote: "No note",
      saving: "Saving",
      save: "Save",
      cancel: "Cancel",
      noteSaved: "Note saved.",
      noArchives: "No archives.",
      cannotSelectProcessing: "Processing archives cannot be selected",
      cannotDeletePublished: "Published archives cannot be deleted",
      selectForDelete: "Select for deletion",
      published: "Published",
      openProduction: "Open production site",
      staging: "Staging",
      openStaging: "Open staging site",
      failedLabel: "Failed",
      processingLabel: "Processing",
      prepareStaging: "Prepare staging site",
      publish: "Publish",
      loadingArchives: "Loading archives...",
      archivesCount: "Archives {count}/{limit}",
      chooseZip: "Choose a ZIP file.",
      signingUpload: "Getting signed URL...",
      uploadingZip: "Uploading ZIP...",
      uploadFailed: "ZIP upload failed.",
      addingArchive: "Adding to archive...",
      archiveAdded: "Added to archive. {count} files",
      prepareStarting: "Starting staging preparation.",
      prepareFailed: "Failed to prepare staging site.",
      preparingStaging: "Preparing staging site.",
      preparedStaging: "Staging site is ready.",
      preparingBeforePublish: "Preparing staging before publishing.",
      confirmPublish: "Publish this archive to {siteName}?",
      publishStarting: "Starting publish.",
      publishFailed: "Publish failed.",
      publishing: "Publishing.",
      publishedToast: "Published. Uploaded {copied} / deleted {deleted}",
      confirmEmpty: "Empty production for {siteName}? You can restore from archives.",
      emptyingProduction: "Emptying production...",
      emptyFailed: "Could not empty production.",
      emptiedProduction: "Production emptied.",
      confirmDelete: "Delete {count} archives?",
      deletingArchives: "Deleting archives...",
      deletedArchives: "Archives deleted.",
      stop: "Stop",
      stopping: "Stopping.",
    },
  };

  const api = (path) => `/sites/${encodeURIComponent(site.siteId)}${path}`;
  const t = (key, values = {}) => {
    const template = messages[lang][key] || messages.ja[key] || key;
    return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{${name}}`, String(value)), template);
  };

  const serverMessage = (message) => {
    if (lang !== "en" || !message) {
      return message;
    }
    const exact = {
      "SITE_HISTORY_BUCKET が未設定です。": "SITE_HISTORY_BUCKET is not configured.",
      "SITE_SIGNED_URL_SERVICE_ACCOUNT または GCP_PROJECT_ID が未設定です。": "SITE_SIGNED_URL_SERVICE_ACCOUNT or GCP_PROJECT_ID is not configured.",
      "ZIP直下に index.html が必要です。": "index.html is required at the ZIP root.",
      "ファイル数が上限を超えています。": "The file count exceeds the limit.",
      "ファイルサイズが上限を超えています。": "A file exceeds the size limit.",
      "総サイズが上限を超えています。": "The total size exceeds the limit.",
      "履歴ZIPのパスが不正です。": "The archive ZIP path is invalid.",
      "stagingに展開できないパスが含まれています。": "The ZIP contains a path that cannot be extracted to staging.",
      "確認サイトが未準備です。先に確認サイトを用意してください。": "The staging site is not ready. Prepare it first.",
      "別のZIPが確認サイトとして準備されています。公開前に確認サイトを用意してください。": "Another ZIP is prepared for staging. Prepare this archive before publishing.",
      "現公開ZIPと現公開内容のファイル一覧が一致しません。": "The current published ZIP and production file list do not match.",
      "現公開ZIPが記録されていません。本番を空にしてから公開してください。": "The current published ZIP is not recorded. Empty production before publishing.",
      "現公開ZIPが見つかりません。本番を空にしてから公開してください。": "The current published ZIP was not found. Empty production before publishing.",
      "サイトが見つかりません。": "Site not found.",
      "公開用GCSバケットが未設定です。": "The public GCS bucket is not configured.",
      "content_type が不正です。": "content_type is invalid.",
      "size_bytes が不正です。": "size_bytes is invalid.",
      "ZIPのサイズが上限を超えています。": "The ZIP size exceeds the limit.",
      "履歴数が上限に達しています。不要な履歴を削除してください。": "The archive limit has been reached. Delete unnecessary archives.",
      "target は staging のみ指定できます。": "target must be staging.",
      "target は prod のみ指定できます。": "target must be prod.",
      "ZIPが見つかりません。": "ZIP not found.",
      "履歴ZIPが見つかりません。": "Archive ZIP not found.",
      "確認サイトの準備に失敗しました。": "Failed to prepare staging site.",
      "公開に失敗しました。": "Publish failed.",
      "本番を空にできませんでした。": "Could not empty production.",
      "削除する履歴を選択してください。": "Select archives to delete.",
      "公開中の履歴は削除できません。": "Published archives cannot be deleted.",
      "メモは500文字以内で入力してください。": "Notes must be 500 characters or fewer.",
      "確認サイトが未準備です。管理画面で確認サイトを用意してください。": "The staging site is not ready. Prepare it in the admin screen.",
      "確認サイトを記録しています。": "Recording staging state.",
      "確認サイトを用意しました。": "Staging site is ready.",
      "確認サイトの準備を開始しています。": "Starting staging preparation.",
      "公開履歴を記録しています。": "Recording publish history.",
      "公開しました。": "Published.",
      "公開を開始しています。": "Starting publish.",
      "本番を空にしました。": "Production emptied.",
      "本番を空にする処理を開始しています。": "Starting production emptying.",
      "空のindex.htmlを設置しています。": "Installing empty index.html.",
      "処理を中止しました。": "Operation stopped.",
      "停止しています。": "Stopping.",
      "実行中の処理はありません。": "No operation is running.",
    };
    if (exact[message]) {
      return exact[message];
    }
    const patterns = [
      [/^ZIPを確認しました。(\d+)件を展開します。$/, "Validated ZIP. Extracting $1 files."],
      [/^確認サイトを空にしています。(\d+)件$/, "Clearing staging site. $1 files"],
      [/^確認サイトへ展開しています。(\d+)\/(\d+)件$/, "Extracting to staging. $1/$2 files"],
      [/^ZIPを確認しました。(\d+)件を公開します。$/, "Validated ZIP. Publishing $1 files."],
      [/^現公開内容を確認しています。(\d+)\/(\d+)件$/, "Checking current production. $1/$2 files"],
      [/^差分を確認しました。送信(\d+)件 \/ 削除(\d+)件 \/ 変更なし(\d+)件$/, "Diff checked. Upload $1 / delete $2 / unchanged $3"],
      [/^公開先へアップロードしています。(\d+)\/(\d+)件$/, "Uploading to production. $1/$2 files"],
      [/^不要な公開ファイルを削除しています。(\d+)件$/, "Deleting obsolete production files. $1 files"],
      [/^公開ファイルを削除しています。(\d+)件$/, "Deleting production files. $1 files"],
      [/^現公開内容のサイズが一致しません: (.+)$/, "Current production size does not match: $1"],
      [/^現公開内容のCRC32が一致しません: (.+)$/, "Current production CRC32 does not match: $1"],
      [/^現公開内容のメタデータサイズが一致しません: (.+)$/, "Current production metadata size does not match: $1"],
    ];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(message)) {
        return message.replace(pattern, replacement);
      }
    }
    return message;
  };

  const setText = (element, text, isError = false) => {
    if (!element) {
      return;
    }
    element.textContent = text || "";
    element.classList.toggle("error", Boolean(isError));
  };

  const showToast = (message) => {
    if (!toast) {
      return;
    }
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
      toast.hidden = true;
    }, 3500);
  };

  const setBusy = (busy) => {
    const changed = isBusy !== busy;
    isBusy = busy;
    [reloadButton, publishEmptyButton].forEach((button) => {
      if (button) {
        button.disabled = busy;
      }
    });
    if (dropZone) {
      dropZone.setAttribute("aria-disabled", busy ? "true" : "false");
    }
    updateDeleteButton();
    if (changed) {
      renderArchives();
    }
  };

  const updateDeleteButton = () => {
    if (deleteButton) {
      deleteButton.disabled = isBusy || selected.size === 0;
    }
  };

  const updateProdEmptyBadge = (isProdEmpty) => {
    if (prodEmptyBadge) {
      prodEmptyBadge.hidden = !isProdEmpty;
    }
  };

  const setArchiveLoading = (loading) => {
    if (archiveLoadingOverlay) {
      archiveLoadingOverlay.hidden = !loading;
    }
  };

  const canCancelKind = (kind) => kind === "publish" || kind === "publish-empty";

  const canStreamKind = (kind) => kind === "publish" || kind === "publish-empty";

  const cancelOperation = async () => {
    if (archiveStatusStop) {
      archiveStatusStop.disabled = true;
      archiveStatusStop.textContent = t("stopping");
    }
    try {
      await requestJson(api("/api/operation/cancel"), { method: "POST" });
    } catch (error) {
      showToast(error.message);
      if (archiveStatusStop) {
        archiveStatusStop.disabled = false;
        archiveStatusStop.textContent = t("stop");
      }
    }
  };

  const setStatusProgress = (message, progress = null, isError = false, cancellable = false) => {
    setText(archiveStatus, message, isError);
    if (!archiveStatusProgress) {
      return;
    }
    archiveStatusProgress.hidden = !message;
    const bar = archiveStatusProgress.querySelector(".archive-progress-bar");
    const fill = archiveStatusProgress.querySelector("span");
    if (!bar || !fill) {
      return;
    }
    bar.classList.toggle("is-indeterminate", !Number.isFinite(progress));
    fill.style.width = Number.isFinite(progress) ? `${progress}%` : "";
    if (archiveStatusStop) {
      archiveStatusStop.hidden = !message || !cancellable;
      archiveStatusStop.disabled = false;
      archiveStatusStop.textContent = t("stop");
    }
  };

  const clearStatusProgress = () => {
    setStatusProgress("");
  };

  const publishedArchiveObjectPath = () => {
    return archives.find((archive) => archive.is_published)?.object_path || "";
  };

  const updateOperationUpdates = (operation) => {
    if (operation && operation.status === "running" && canStreamKind(operation.kind)) {
      if (archivePollTimer) {
        window.clearInterval(archivePollTimer);
        archivePollTimer = null;
      }
      startOperationStream(operation);
      return;
    }
    if (operationStreamController && (!operation || operation.status !== "running")) {
      operationStreamController.abort();
      operationStreamController = null;
      operationStreamId = "";
    }
    if (archivePollTimer && (!operation || operation.status !== "running")) {
      window.clearInterval(archivePollTimer);
      archivePollTimer = null;
    }
    if (operation && operation.status === "running" && !archivePollTimer) {
      archivePollTimer = window.setInterval(() => {
        pollOperation();
      }, 700);
    }
  };

  const applyOperation = (operation) => {
    updateOperationUpdates(operation);
    if (!operation) {
      lastAppliedOperationKey = "";
      return;
    }
    const operationKey = [
      operation.operation_id,
      operation.kind,
      operation.object_path,
      operation.status,
      operation.message,
      operation.progress,
      operation.cancel_requested,
    ].join("|");
    if (operationKey === lastAppliedOperationKey) {
      return;
    }
    lastAppliedOperationKey = operationKey;
    const isError = operation.status === "error";
    if (operation.object_path) {
      setArchiveProcessingStatus(
        operation.object_path,
        serverMessage(operation.message) || t("busy"),
        operation.progress,
        isError,
        operation.kind,
        Boolean(operation.cancel_requested),
      );
      return;
    }
    const message = serverMessage(operation.message) || t("busy");
    if (operation.kind === "publish-empty") {
      const objectPath = publishedArchiveObjectPath();
      if (objectPath) {
        setArchiveProcessingStatus(objectPath, message, operation.progress, isError, operation.kind, Boolean(operation.cancel_requested));
        return;
      }
      setStatusProgress(message, operation.progress, isError, operation.kind === "publish-empty" && !operation.cancel_requested);
      return;
    }
    setText(archiveStatus, message, isError);
  };

  const pollOperation = async () => {
    try {
      const payload = await requestJson(api("/api/operation"));
      applyOperation(payload.operation);
      if (!payload.operation || payload.operation.status !== "running") {
        await loadArchives({ clearStatuses: false });
      }
    } catch (error) {
      setText(archiveStatus, error.message, true);
    }
  };

  const operationProgressTarget = (operation) => {
    if (!operation) {
      return null;
    }
    if (operation.object_path) {
      return { type: "archive", objectPath: operation.object_path, kind: operation.kind };
    }
    if (operation.kind === "publish-empty") {
      const objectPath = publishedArchiveObjectPath();
      if (objectPath) {
        return { type: "archive", objectPath, kind: operation.kind };
      }
      return { type: "status", kind: operation.kind };
    }
    return { type: "status", kind: operation.kind };
  };

  const updateOperationProgress = (target, message, progress, isError = false, cancelRequested = false) => {
    if (!target) {
      setText(archiveStatus, message, isError);
      return;
    }
    if (target.type === "archive") {
      setArchiveProcessingStatus(target.objectPath, message, progress, isError, target.kind, cancelRequested);
      return;
    }
    setStatusProgress(message, progress, isError, canCancelKind(target.kind) && !cancelRequested);
  };

  const handleOperationStreamEvent = async (operation, event) => {
    if (event.status === "idle") {
      await loadArchives();
      return true;
    }
    const target = operationProgressTarget(operation);
    if (event.status === "error") {
      updateOperationProgress(target, serverMessage(event.message) || t("failed"), event.progress, true);
      await loadArchives({ clearStatuses: false });
      return true;
    }
    if (event.status === "cancelled") {
      updateOperationProgress(target, serverMessage(event.message) || t("done"), event.progress, false, true);
      await loadArchives();
      return true;
    }
    if (event.status === "ok") {
      updateOperationProgress(target, t("done"), 100);
      await loadArchives();
      return true;
    }
    updateOperationProgress(target, serverMessage(event.message) || t("busy"), event.progress);
    return false;
  };

  const startOperationStream = async (operation) => {
    if (!operation || operationStreamId === operation.operation_id) {
      return;
    }
    if (operationStreamController) {
      operationStreamController.abort();
    }
    operationStreamId = operation.operation_id;
    operationStreamController = new AbortController();
    const controller = operationStreamController;
    try {
      const response = await fetch(api("/api/operation/stream"), {
        method: "POST",
        signal: controller.signal,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(serverMessage(payload.detail) || t("failed"));
      }
      if (!response.body) {
        throw new Error(t("progressReadFailed"));
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let shouldClose = false;
      while (!shouldClose) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) {
            continue;
          }
          shouldClose = await handleOperationStreamEvent(operation, JSON.parse(line));
          if (shouldClose) {
            break;
          }
        }
        if (done) {
          break;
        }
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        setText(archiveStatus, error.message, true);
      }
    } finally {
      if (operationStreamController === controller) {
        operationStreamController = null;
        operationStreamId = "";
      }
    }
  };

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(serverMessage(payload.detail) || t("failed"));
    }
    return payload;
  };

  const readProgressStream = async (response, objectPath, fallbackMessage) => {
    if (!response.body) {
      throw new Error(t("progressReadFailed"));
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completedPayload = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }
        const event = JSON.parse(line);
        if (event.status === "error") {
          throw new Error(serverMessage(event.message) || t("failed"));
        }
        if (event.status === "cancelled") {
          completedPayload = event;
          setArchiveProcessingStatus(objectPath, serverMessage(event.message) || t("done"), event.progress, false, "publish");
          continue;
        }
        if (event.status === "ok") {
          completedPayload = event;
          setArchiveProcessingStatus(objectPath, t("done"), 100, false, "publish");
          continue;
        }
        setArchiveProcessingStatus(objectPath, serverMessage(event.message) || fallbackMessage, event.progress, false, "publish");
      }
      if (done) {
        break;
      }
    }
    if (!completedPayload) {
      throw new Error(t("completionUnknown"));
    }
    return completedPayload;
  };

  const readStatusProgressStream = async (response, fallbackMessage, onProgress) => {
    if (!response.body) {
      throw new Error(t("progressReadFailed"));
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completedPayload = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }
        const event = JSON.parse(line);
        if (event.status === "error") {
          throw new Error(serverMessage(event.message) || t("failed"));
        }
        if (event.status === "cancelled") {
          completedPayload = event;
          onProgress(serverMessage(event.message) || t("done"), event.progress, false);
          continue;
        }
        if (event.status === "ok") {
          completedPayload = event;
          onProgress(t("done"), 100, false);
          continue;
        }
        onProgress(serverMessage(event.message) || fallbackMessage, event.progress, false);
      }
      if (done) {
        break;
      }
    }
    if (!completedPayload) {
      throw new Error(t("completionUnknown"));
    }
    return completedPayload;
  };

  const archiveApiPath = (objectPath) => {
    const prefix = `sites/${site.siteId}/archive/`;
    return objectPath.replace(prefix, "").split("/").map(encodeURIComponent).join("/");
  };

  const formatSize = (size) => {
    if (!Number.isFinite(size)) {
      return "";
    }
    if (size >= 1024 * 1024) {
      return `${(size / 1024 / 1024).toFixed(1)} MB`;
    }
    if (size >= 1024) {
      return `${(size / 1024).toFixed(1)} KB`;
    }
    return `${size} B`;
  };

  const formatDate = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value || "";
    }
    return date.toLocaleString(lang === "en" ? "en-US" : "ja-JP");
  };

  const createButton = (label, className, onClick, disabled = isBusy, icon = null) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    if (icon) {
      const text = document.createElement("span");
      text.textContent = label;
      button.append(icon, text);
    } else {
      button.textContent = label;
    }
    button.disabled = disabled;
    button.addEventListener("click", onClick);
    return button;
  };

  const createLinkButton = (label, href) => {
    const link = document.createElement("a");
    link.className = "button secondary";
    link.textContent = label;
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    return link;
  };

  const externalIcon = () => svgIcon('<path d="M14 5h5v5"></path><path d="M10 14 19 5"></path><path d="M19 14v5H5V5h5"></path>');

  const createBadgeLink = (href, text, className, tooltip) => {
    const link = document.createElement("a");
    link.className = className;
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = tooltip;
    link.setAttribute("aria-label", tooltip);
    const label = document.createElement("span");
    label.textContent = text;
    link.append(label, externalIcon());
    return link;
  };

  const svgIcon = (paths) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = paths;
    return svg;
  };

  const downloadIcon = () => svgIcon('<path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path>');

  const inspectIcon = () => svgIcon('<circle cx="11" cy="11" r="6"></circle><path d="m16 16 5 5"></path>');

  const publishIcon = () => svgIcon('<path d="M12 21V9"></path><path d="m7 14 5-5 5 5"></path><path d="M5 5h14"></path>');

  const createDownloadLink = (href) => {
    const link = document.createElement("a");
    link.className = "icon-tool-button";
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = t("downloadZip");
    link.setAttribute("aria-label", t("downloadZip"));
    link.append(downloadIcon());
    return link;
  };

  const createIconButton = (label, icon, onClick, disabled = isBusy) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-tool-button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.disabled = disabled;
    button.append(icon);
    button.addEventListener("click", onClick);
    return button;
  };

  const renderNote = (archive, meta) => {
    const note = document.createElement("button");
    note.type = "button";
    note.className = "archive-note button secondary small";
    note.classList.toggle("is-empty", !archive.note);
    note.textContent = archive.note || t("noNote");
    note.addEventListener("click", () => {
      const editor = document.createElement("div");
      editor.className = "archive-note-edit";
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = 500;
      input.value = archive.note || "";
      const spinner = document.createElement("span");
      spinner.className = "inline-spinner";
      spinner.setAttribute("aria-label", t("saving"));
      spinner.hidden = true;
      const save = createButton(t("save"), "button primary small", async () => {
        try {
          save.disabled = true;
          cancel.disabled = true;
          input.disabled = true;
          spinner.hidden = false;
          editor.classList.add("is-saving");
          const payload = await requestJson(api(`/api/archives/${archiveApiPath(archive.object_path)}/note`), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note: input.value }),
          });
          archive.note = payload.note;
          showToast(t("noteSaved"));
          renderArchives();
        } catch (error) {
          showToast(error.message);
          save.disabled = false;
          cancel.disabled = false;
          input.disabled = false;
          spinner.hidden = true;
          editor.classList.remove("is-saving");
          input.focus();
        }
      });
      const cancel = createButton(t("cancel"), "button secondary small", () => renderArchives());
      editor.append(input, save, cancel, spinner);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          save.click();
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancel.click();
        }
      });
      note.replaceWith(editor);
      input.focus();
    });
    meta.append(note);
  };

  const renderArchives = () => {
    archivesList.textContent = "";
    const displayArchives = [...processingArchives, ...archives];
    selected = new Set(Array.from(selected).filter((objectPath) => {
      return archives.some((archive) => archive.object_path === objectPath && !archive.is_published);
    }));
    updateDeleteButton();

    if (!displayArchives.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = t("noArchives");
      archivesList.append(empty);
      return;
    }

    displayArchives.forEach((archive) => {
      const rowStatus = archive.is_processing
        ? { message: archive.processing_status || t("busy"), progress: archive.processing_progress, isError: archive.is_error, kind: archive.processing_kind }
        : archiveProcessingStatuses.get(archive.object_path);
      const isRowProcessing = Boolean(rowStatus);
      const row = document.createElement("div");
      row.className = "archive-row";
      if (isRowProcessing) {
        row.classList.add(rowStatus.isError ? "is-error" : "is-processing");
      }

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = archive.object_path;
      checkbox.checked = selected.has(archive.object_path);
      checkbox.disabled = isRowProcessing || archive.is_published || isBusy;
      checkbox.title = isRowProcessing
        ? t("cannotSelectProcessing")
        : archive.is_published
          ? t("cannotDeletePublished")
          : t("selectForDelete");
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          selected.add(archive.object_path);
        } else {
          selected.delete(archive.object_path);
        }
        updateDeleteButton();
      });

      const meta = document.createElement("div");
      meta.className = "archive-meta";

      const name = document.createElement("div");
      name.className = "archive-name";
      const strong = document.createElement("strong");
      strong.textContent = archive.filename || archive.object_path;
      strong.title = archive.object_path;
      name.append(strong);
      if (archive.is_published) {
        if (site.publicUrl) {
          name.append(createBadgeLink(site.publicUrl, t("published"), "badge", t("openProduction")));
        } else {
          const badge = document.createElement("span");
          badge.className = "badge";
          badge.textContent = t("published");
          name.append(badge);
        }
      }
      if (archive.object_path === preparedObjectPath) {
        name.append(createBadgeLink(api("/staging/"), t("staging"), "badge staging", t("openStaging")));
      }

      const detail = document.createElement("div");
      detail.className = "archive-detail";
      detail.textContent = isRowProcessing
        ? rowStatus.message
        : `${formatDate(archive.created_at)} / ${formatSize(archive.size_bytes)}`;

      meta.append(name, detail);
      if (isRowProcessing) {
        const progress = document.createElement("div");
        progress.className = "archive-progress";
        const bar = document.createElement("div");
        bar.className = "archive-progress-bar";
        const fill = document.createElement("span");
        if (Number.isFinite(rowStatus.progress)) {
          fill.style.width = `${rowStatus.progress}%`;
        } else {
          bar.classList.add("is-indeterminate");
        }
        bar.append(fill);
        progress.append(bar);
        meta.append(progress);
      } else {
        renderNote(archive, meta);
      }

      const actions = document.createElement("div");
      actions.className = "archive-actions";
      if (isRowProcessing) {
        const status = document.createElement("span");
        status.className = "archive-action-status";
        status.textContent = rowStatus.isError ? t("failedLabel") : t("processingLabel");
        actions.append(status);
        if (canCancelKind(rowStatus.kind) && !rowStatus.cancelRequested) {
          actions.append(createButton(t("stop"), "button danger small", cancelOperation, false));
        }
      } else {
        actions.append(
          createIconButton(t("prepareStaging"), inspectIcon(), () => prepareArchive(archive.object_path), isBusy),
          createDownloadLink(api(`/api/archives/${archiveApiPath(archive.object_path)}/download`)),
          createButton(
            t("publish"),
            "button primary small",
            () => publishArchive(archive.object_path),
            isBusy,
            publishIcon(),
          ),
        );
      }

      row.append(checkbox, meta, actions);
      archivesList.append(row);
    });
  };

  const addProcessingArchive = (file, message, progress = null) => {
    const objectPath = `__processing__/${Date.now()}`;
    processingArchives = [{
      object_path: objectPath,
      filename: file.name,
      created_at: new Date().toISOString(),
      size_bytes: file.size,
      is_processing: true,
      is_error: false,
      processing_status: message,
      processing_progress: progress,
    }, ...processingArchives];
    renderArchives();
    return objectPath;
  };

  const updateProcessingArchive = (objectPath, message, progress = null, isError = false) => {
    processingArchives = processingArchives.map((archive) => {
      if (archive.object_path !== objectPath) {
        return archive;
      }
      return {
        ...archive,
        is_error: isError,
        processing_status: message,
        processing_progress: progress,
      };
    });
    renderArchives();
  };

  const setArchiveProcessingStatus = (objectPath, message, progress = null, isError = false, kind = "", cancelRequested = false) => {
    archiveProcessingStatuses.set(objectPath, {
      message,
      progress,
      isError,
      kind,
      cancelRequested,
    });
    renderArchives();
  };

  const clearArchiveProcessingStatus = (objectPath) => {
    archiveProcessingStatuses.delete(objectPath);
    renderArchives();
  };

  const clearArchiveProcessingStatuses = () => {
    archiveProcessingStatuses = new Map();
    renderArchives();
  };

  const removeProcessingArchive = (objectPath) => {
    processingArchives = processingArchives.filter((archive) => archive.object_path !== objectPath);
    renderArchives();
  };

  const loadArchives = async (options = {}) => {
    const clearStatuses = options.clearStatuses !== false;
    const quiet = Boolean(options.quiet);
    if (!quiet) {
      setBusy(true);
    }
    if (clearStatuses) {
      clearArchiveProcessingStatuses();
    }
    if (!quiet) {
      clearStatusProgress();
      setText(archiveStatus, t("loadingArchives"));
      setArchiveLoading(true);
    }
    try {
      const payload = await requestJson(api("/api/archives"));
      archives = payload.archives || [];
      preparedObjectPath = payload.prepared_object_path || "";
      updateProdEmptyBadge(Boolean(payload.is_prod_empty));
      setText(archiveStatus, t("archivesCount", { count: archives.length, limit: payload.archive_limit }));
      renderArchives();
      applyOperation(payload.operation);
    } catch (error) {
      setText(archiveStatus, error.message, true);
    } finally {
      if (!quiet) {
        setArchiveLoading(false);
        setBusy(false);
      }
    }
  };

  const uploadZip = async (file) => {
    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setText(uploadStatus, t("chooseZip"), true);
      return;
    }
    setBusy(true);
    setText(uploadStatus, "");
    const processingObjectPath = addProcessingArchive(file, t("signingUpload"), 5);
    try {
      const signPayload = await requestJson(api("/api/sign-upload"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/zip",
          size_bytes: file.size,
        }),
      });
      updateProcessingArchive(processingObjectPath, t("uploadingZip"), 35);
      const uploadResponse = await fetch(signPayload.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/zip" },
        body: file,
      });
      if (!uploadResponse.ok) {
        throw new Error(t("uploadFailed"));
      }
      updateProcessingArchive(processingObjectPath, t("addingArchive"), 75);
      const deployPayload = await requestJson(api("/api/deploy"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          object_path: signPayload.object_path,
          target: "staging",
          original_filename: file.name,
        }),
      });
      updateProcessingArchive(processingObjectPath, t("archiveAdded", { count: deployPayload.file_count }), 100);
      removeProcessingArchive(processingObjectPath);
      await loadArchives();
    } catch (error) {
      updateProcessingArchive(processingObjectPath, error.message, null, true);
    } finally {
      setBusy(false);
      fileInput.value = "";
    }
  };

  const prepareArchive = async (objectPath) => {
    setBusy(true);
    setArchiveProcessingStatus(objectPath, t("prepareStarting"), 0);
    try {
      const response = await fetch(api("/api/prepare-staging"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_path: objectPath, target: "staging" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(serverMessage(payload.detail) || t("prepareFailed"));
      }
      await readProgressStream(response, objectPath, t("preparingStaging"));
      clearArchiveProcessingStatus(objectPath);
      showToast(t("preparedStaging"));
      await loadArchives();
    } catch (error) {
      setArchiveProcessingStatus(objectPath, error.message, null, true);
    } finally {
      setBusy(false);
    }
  };

  const prepareArchiveForPublish = async (objectPath) => {
    const response = await fetch(api("/api/prepare-staging"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ object_path: objectPath, target: "staging" }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(serverMessage(payload.detail) || t("prepareFailed"));
    }
    await readProgressStream(response, objectPath, t("preparingBeforePublish"));
    preparedObjectPath = objectPath;
  };

  const publishArchive = async (objectPath) => {
    if (!window.confirm(t("confirmPublish", { siteName: site.siteName }))) {
      return;
    }
    setBusy(true);
    setArchiveProcessingStatus(objectPath, t("publishStarting"), 0, false, "publish");
    try {
      if (objectPath !== preparedObjectPath) {
        setArchiveProcessingStatus(objectPath, t("preparingBeforePublish"), 0, false, "publish");
        await prepareArchiveForPublish(objectPath);
      }
      setArchiveProcessingStatus(objectPath, t("publishStarting"), 0, false, "publish");
      const response = await fetch(api("/api/publish"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_path: objectPath, target: "prod" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(serverMessage(payload.detail) || t("publishFailed"));
      }
      const payload = await readProgressStream(response, objectPath, t("publishing"));
      if (payload.status === "cancelled") {
        await loadArchives();
        return;
      }
      clearArchiveProcessingStatus(objectPath);
      showToast(t("publishedToast", { copied: payload.copied_count, deleted: payload.deleted_count }));
      await loadArchives();
    } catch (error) {
      setArchiveProcessingStatus(objectPath, error.message, null, true);
    } finally {
      setBusy(false);
    }
  };

  const publishEmpty = async () => {
    if (!window.confirm(t("confirmEmpty", { siteName: site.siteName }))) {
      return;
    }
    setBusy(true);
    clearArchiveProcessingStatuses();
    const publishedObjectPath = publishedArchiveObjectPath();
    const updateEmptyProgress = (message, progress, isError = false) => {
      if (publishedObjectPath) {
        setArchiveProcessingStatus(publishedObjectPath, message, progress, isError, "publish-empty");
      } else {
        setStatusProgress(message, progress, isError, true);
      }
    };
    updateEmptyProgress(t("emptyingProduction"), 0);
    try {
      const response = await fetch(api("/api/publish-empty"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: "prod" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(serverMessage(payload.detail) || t("emptyFailed"));
      }
      const payload = await readStatusProgressStream(response, t("emptyingProduction"), updateEmptyProgress);
      if (payload.status === "cancelled") {
        await loadArchives();
        return;
      }
      showToast(t("emptiedProduction"));
      if (!publishedObjectPath) {
        clearStatusProgress();
      }
      await loadArchives();
    } catch (error) {
      updateEmptyProgress(error.message, null, true);
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    const objectPaths = Array.from(selected);
    if (!objectPaths.length) {
      return;
    }
    if (!window.confirm(t("confirmDelete", { count: objectPaths.length }))) {
      return;
    }
    setBusy(true);
    setText(archiveStatus, t("deletingArchives"));
    try {
      await requestJson(api("/api/archives/delete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_paths: objectPaths }),
      });
      selected = new Set();
      showToast(t("deletedArchives"));
      await loadArchives();
    } catch (error) {
      setText(archiveStatus, error.message, true);
    } finally {
      setBusy(false);
    }
  };

  const hasDraggedFiles = (event) => {
    return Array.from(event.dataTransfer?.types || []).includes("Files");
  };

  const setPageDragover = (dragover) => {
    pageDragDepth = dragover ? Math.max(pageDragDepth, 1) : 0;
    dropZone.classList.toggle("is-dragover", dragover);
  };

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  document.addEventListener("dragenter", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }
    event.preventDefault();
    pageDragDepth += 1;
    dropZone.classList.add("is-dragover");
  });
  document.addEventListener("dragover", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setPageDragover(true);
  });
  document.addEventListener("dragleave", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }
    pageDragDepth = Math.max(pageDragDepth - 1, 0);
    if (pageDragDepth === 0) {
      dropZone.classList.remove("is-dragover");
    }
  });
  document.addEventListener("drop", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }
    event.preventDefault();
    setPageDragover(false);
    uploadZip(event.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => uploadZip(fileInput.files[0]));
  reloadButton.addEventListener("click", loadArchives);
  deleteButton.addEventListener("click", deleteSelected);
  publishEmptyButton.addEventListener("click", publishEmpty);
  if (archiveStatusStop) {
    archiveStatusStop.addEventListener("click", cancelOperation);
  }

  loadArchives();
})();
