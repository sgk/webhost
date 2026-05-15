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
  const archivesList = document.getElementById("archives-list");
  const toast = document.getElementById("toast");
  let archives = [];
  let selected = new Set();
  let preparedObjectPath = "";
  let isBusy = false;
  let processingArchives = [];
  let archiveProcessingStatuses = new Map();

  const api = (path) => `/sites/${encodeURIComponent(site.siteId)}${path}`;

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

  const requestJson = async (url, options = {}) => {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "処理に失敗しました。");
    }
    return payload;
  };

  const readProgressStream = async (response, objectPath, fallbackMessage) => {
    if (!response.body) {
      throw new Error("処理の進捗を読み込めませんでした。");
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
          throw new Error(event.message || "処理に失敗しました。");
        }
        if (event.status === "ok") {
          completedPayload = event;
          setArchiveProcessingStatus(objectPath, "完了しました。", 100);
          continue;
        }
        setArchiveProcessingStatus(objectPath, event.message || fallbackMessage, event.progress);
      }
      if (done) {
        break;
      }
    }
    if (!completedPayload) {
      throw new Error("処理の完了を確認できませんでした。");
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
    return date.toLocaleString("ja-JP");
  };

  const createButton = (label, className, onClick, disabled = isBusy) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
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

  const createDownloadLink = (href) => {
    const link = document.createElement("a");
    link.className = "icon-tool-button";
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = "履歴ZIPをダウンロード";
    link.setAttribute("aria-label", "履歴ZIPをダウンロード");
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
    note.textContent = archive.note || "メモなし";
    note.addEventListener("click", () => {
      const editor = document.createElement("div");
      editor.className = "archive-note-edit";
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = 500;
      input.value = archive.note || "";
      const spinner = document.createElement("span");
      spinner.className = "inline-spinner";
      spinner.setAttribute("aria-label", "保存中");
      spinner.hidden = true;
      const save = createButton("保存", "button primary small", async () => {
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
          showToast("メモを保存しました。");
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
      const cancel = createButton("キャンセル", "button secondary small", () => renderArchives());
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
      empty.textContent = "履歴はありません。";
      archivesList.append(empty);
      return;
    }

    displayArchives.forEach((archive) => {
      const rowStatus = archive.is_processing
        ? { message: archive.processing_status || "処理しています...", progress: archive.processing_progress, isError: archive.is_error }
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
        ? "処理中の履歴は選択できません"
        : archive.is_published
          ? "公開中の履歴は削除できません"
          : "削除対象にする";
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
          name.append(createBadgeLink(site.publicUrl, "公開中", "badge", "本番サイトを開く"));
        } else {
          const badge = document.createElement("span");
          badge.className = "badge";
          badge.textContent = "公開中";
          name.append(badge);
        }
      }
      if (archive.object_path === preparedObjectPath) {
        name.append(createBadgeLink(api("/staging/"), "確認中", "badge staging", "確認サイトを開く"));
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
        status.textContent = rowStatus.isError ? "失敗" : "処理中";
        actions.append(status);
      } else {
        actions.append(
          createIconButton("確認サイトを用意する", inspectIcon(), () => prepareArchive(archive.object_path), isBusy),
          createDownloadLink(api(`/api/archives/${archiveApiPath(archive.object_path)}/download`)),
          createButton(
            "公開する",
            "button primary small",
            () => publishArchive(archive.object_path),
            isBusy,
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

  const setArchiveProcessingStatus = (objectPath, message, progress = null, isError = false) => {
    archiveProcessingStatuses.set(objectPath, {
      message,
      progress,
      isError,
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

  const loadArchives = async () => {
    setBusy(true);
    clearArchiveProcessingStatuses();
    setText(archiveStatus, "履歴を読み込んでいます...");
    try {
      const payload = await requestJson(api("/api/archives"));
      archives = payload.archives || [];
      preparedObjectPath = payload.prepared_object_path || "";
      updateProdEmptyBadge(Boolean(payload.is_prod_empty));
      setText(archiveStatus, `履歴 ${archives.length}/${payload.archive_limit} 件`);
      renderArchives();
    } catch (error) {
      setText(archiveStatus, error.message, true);
    } finally {
      setBusy(false);
    }
  };

  const uploadZip = async (file) => {
    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setText(uploadStatus, "ZIPファイルを選択してください。", true);
      return;
    }
    setBusy(true);
    setText(uploadStatus, "");
    const processingObjectPath = addProcessingArchive(file, "署名付きURLを取得しています...", 5);
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
      updateProcessingArchive(processingObjectPath, "ZIPをアップロードしています...", 35);
      const uploadResponse = await fetch(signPayload.upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/zip" },
        body: file,
      });
      if (!uploadResponse.ok) {
        throw new Error("ZIPのアップロードに失敗しました。");
      }
      updateProcessingArchive(processingObjectPath, "履歴に追加しています...", 75);
      const deployPayload = await requestJson(api("/api/deploy"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          object_path: signPayload.object_path,
          target: "staging",
          original_filename: file.name,
        }),
      });
      updateProcessingArchive(processingObjectPath, `履歴に追加しました。${deployPayload.file_count}件`, 100);
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
    setArchiveProcessingStatus(objectPath, "確認サイトの準備を開始しています。", 0);
    try {
      const response = await fetch(api("/api/prepare-staging"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_path: objectPath, target: "staging" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "確認サイトの準備に失敗しました。");
      }
      await readProgressStream(response, objectPath, "確認サイトを用意しています。");
      clearArchiveProcessingStatus(objectPath);
      showToast("確認サイトを用意しました。");
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
      throw new Error(payload.detail || "確認サイトの準備に失敗しました。");
    }
    await readProgressStream(response, objectPath, "公開前に確認サイトを用意しています。");
    preparedObjectPath = objectPath;
  };

  const publishArchive = async (objectPath) => {
    if (!window.confirm(`${site.siteName} にこの履歴を公開します。よろしいですか？`)) {
      return;
    }
    setBusy(true);
    setArchiveProcessingStatus(objectPath, "公開を開始しています。", 0);
    try {
      if (objectPath !== preparedObjectPath) {
        setArchiveProcessingStatus(objectPath, "公開前に確認サイトを用意しています。", 0);
        await prepareArchiveForPublish(objectPath);
      }
      setArchiveProcessingStatus(objectPath, "公開を開始しています。", 0);
      const response = await fetch(api("/api/publish"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_path: objectPath, target: "prod" }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "公開に失敗しました。");
      }
      const payload = await readProgressStream(response, objectPath, "公開しています。");
      clearArchiveProcessingStatus(objectPath);
      showToast(`公開しました。送信${payload.copied_count}件 / 削除${payload.deleted_count}件`);
      await loadArchives();
    } catch (error) {
      setArchiveProcessingStatus(objectPath, error.message, null, true);
    } finally {
      setBusy(false);
    }
  };

  const publishEmpty = async () => {
    if (!window.confirm(`${site.siteName} の本番を空にします。履歴から復旧できます。よろしいですか？`)) {
      return;
    }
    setBusy(true);
    clearArchiveProcessingStatuses();
    setText(archiveStatus, "本番を空にしています...");
    try {
      await requestJson(api("/api/publish-empty"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: "prod" }),
      });
      showToast("本番を空にしました。");
      setText(archiveStatus, "");
      await loadArchives();
    } catch (error) {
      setText(archiveStatus, error.message, true);
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    const objectPaths = Array.from(selected);
    if (!objectPaths.length) {
      return;
    }
    if (!window.confirm(`${objectPaths.length}件の履歴を削除します。よろしいですか？`)) {
      return;
    }
    setBusy(true);
    setText(archiveStatus, "履歴を削除しています...");
    try {
      await requestJson(api("/api/archives/delete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_paths: objectPaths }),
      });
      selected = new Set();
      showToast("履歴を削除しました。");
      await loadArchives();
    } catch (error) {
      setText(archiveStatus, error.message, true);
    } finally {
      setBusy(false);
    }
  };

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("is-dragover"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragover");
    uploadZip(event.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => uploadZip(fileInput.files[0]));
  reloadButton.addEventListener("click", loadArchives);
  deleteButton.addEventListener("click", deleteSelected);
  publishEmptyButton.addEventListener("click", publishEmpty);

  loadArchives();
})();
