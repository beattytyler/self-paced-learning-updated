document.addEventListener("DOMContentLoaded", function () {
  // Get all topic buttons
  const topicButtons = document.querySelectorAll(".button[data-topic]");
  const closeButton = document.querySelector(".close-button");
  const videoModal = document.getElementById("video-modal");
  const videoIframe = document.getElementById("video-iframe");
  const videoTitle = document.getElementById("current-video-title");
  const adminOverrideIndicator = document.getElementById(
    "adminOverrideIndicator"
  );
  const adminOverrideIndicatorText = document.getElementById(
    "adminOverrideIndicatorText"
  );
  const adminOverrideIndicatorWrapper = document.querySelector(
    ".admin-override-indicator-wrapper"
  );

  // YouTube API variables
  let ytPlayer = null;
  let isAdminOverride = false;
  let currentVideoId = null;
  let currentVideoKey = null;
  let currentTopic = null;

  // Load progress from server when page loads
  loadProgress();

  // Initialize admin override indicator state from markup if available
  if (adminOverrideIndicator) {
    const initialState = adminOverrideIndicator.dataset.active === "true";
    isAdminOverride = initialState;
    updateAdminOverrideIndicator(initialState);
  }

  // Check if user is admin
  checkAdminStatus();

  // Add click event to all topic buttons
  topicButtons.forEach((button) => {
    button.addEventListener("click", function () {
      const topic = this.getAttribute("data-topic");
      openVideo(topic);
    });
  });

  // Close video modal
  closeButton.addEventListener("click", function () {
    closeVideo();
  });

  // Close modal when clicking outside the video
  videoModal.addEventListener("click", function (e) {
    if (e.target === videoModal) {
      closeVideo();
    }
  });

  // Check if user has admin privileges
  function checkAdminStatus() {
    fetch("/api/admin/status")
      .then((response) => response.json())
      .then((data) => {
        let overrideActive = false;

        if (data && typeof data.admin_override === "boolean") {
          overrideActive = data.admin_override;
        } else if (
          data && typeof data.is_admin_override === "boolean"
        ) {
          overrideActive = data.is_admin_override;
        } else if (data && typeof data.is_admin === "boolean") {
          overrideActive = data.is_admin;
        }

        isAdminOverride = overrideActive;
        updateAdminOverrideIndicator(overrideActive);
      })
      .catch(() => {
        isAdminOverride = false;
        updateAdminOverrideIndicator(false);
      });
  }

  function updateAdminOverrideIndicator(isActive) {
    if (!adminOverrideIndicator || !adminOverrideIndicatorText) {
      return;
    }

    if (adminOverrideIndicatorWrapper) {
      adminOverrideIndicatorWrapper.classList.toggle("is-hidden", !isActive);
    }

    if (isActive) {
      adminOverrideIndicator.classList.add("active");
      adminOverrideIndicator.dataset.active = "true";
      adminOverrideIndicatorText.textContent = "Admin Override Active";
    } else {
      adminOverrideIndicator.classList.remove("active");
      adminOverrideIndicator.dataset.active = "false";
      adminOverrideIndicatorText.textContent = "Admin Override Off";
    }
  }

  // YouTube API ready callback
  function onYouTubeIframeAPIReady() {
    // YouTube API is ready
  }

  // Initialize YouTube player with enhanced tracking
  function initializePlayer(videoId, elementId) {
    if (ytPlayer) {
      ytPlayer.destroy();
    }

    ytPlayer = new YT.Player(elementId, {
      height: "400",
      width: "100%",
      videoId: videoId,
      playerVars: {
        autoplay: 1,
        controls: 1,
        rel: 0,
        showinfo: 0,
        modestbranding: 1,
      },
      events: {
        onReady: onPlayerReady,
        onStateChange: onPlayerStateChange,
      },
    });
  }

  function onPlayerReady(event) {
    startVideoProgressTracking();
  }

  function onPlayerStateChange(event) {
    if (event.data == YT.PlayerState.ENDED) {
      handleVideoComplete();
    }
  }

  // Start enhanced video progress tracking
  function startVideoProgressTracking() {
    if (!ytPlayer || !currentTopic) return;

    let videoWatchedMarked = false; // Flag to prevent multiple API calls

    const trackingInterval = setInterval(() => {
      if (!ytPlayer || ytPlayer.getPlayerState() === YT.PlayerState.UNSTARTED) {
        clearInterval(trackingInterval);
        return;
      }

      const currentTime = ytPlayer.getCurrentTime();
      const duration = ytPlayer.getDuration();

      if (duration > 0) {
        const progress = Math.min((currentTime / duration) * 100, 100);
        updateVideoProgress(currentTopic, progress);

        // Mark video as watched at 80% completion (for quiz prerequisites)
        if (!videoWatchedMarked && progress >= 80) {
          videoWatchedMarked = true;
          markVideoAsWatched();
        }

        // Auto-complete for admins at 80% or if override enabled
        if (isAdminOverride && progress >= 80) {
          handleVideoComplete();
          clearInterval(trackingInterval);
        }
      }
    }, 2000); // Check every 2 seconds

    // Store interval reference for cleanup
    videoModal.dataset.trackingInterval = trackingInterval;
  }

  function getCurrentVideoContext() {
    const currentPath = window.location.pathname;
    if (!currentPath.startsWith("/subjects/")) {
      return null;
    }

    const pathParts = currentPath.split("/");
    const subject = pathParts[2];
    const subtopic = currentTopic;
    const videoId = currentVideoKey || currentTopic || currentVideoId;

    if (!subject || !subtopic || !videoId) {
      return null;
    }

    return { subject, subtopic, videoId };
  }

  function recordVideoOpened(context) {
    const details = context || getCurrentVideoContext();
    if (!details) {
      return;
    }

    const cacheKey = `${details.subject}::${details.subtopic}::${details.videoId}`;
    if (!recordVideoOpened.cache) {
      recordVideoOpened.cache = new Set();
    }

    if (recordVideoOpened.cache.has(cacheKey)) {
      return;
    }

    recordVideoOpened.cache.add(cacheKey);

    fetch("/api/progress/update", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        subject: details.subject,
        subtopic: details.subtopic,
        item_id: details.videoId,
        item_type: "video",
      }),
    })
      .then((response) => response.json().catch(() => ({})))
      .then((data) => {
        if (!data || !data.success) {
          recordVideoOpened.cache.delete(cacheKey);
        }
      })
      .catch(() => {
        recordVideoOpened.cache.delete(cacheKey);
      });
  }

  // Mark video as watched for quiz prerequisites
  function markVideoAsWatched() {
    const context = getCurrentVideoContext();
    if (!context) {
      return;
    }

    recordVideoOpened(context);

    if (typeof showNotification === "function") {
      showNotification(
        "Video progress recorded! This counts toward quiz prerequisites.",
        "success"
      );
    }
    if (typeof updateSubtopicProgressAfterCompletion === "function") {
      updateSubtopicProgressAfterCompletion();
    }
  }

  function handleVideoComplete() {
    if (currentTopic) {
      saveProgress(currentTopic, 100);

      recordVideoOpened();

      showVideoCompletionNotification();
      if (typeof updateSubtopicProgressAfterCompletion === "function") {
        updateSubtopicProgressAfterCompletion();
      }

      // Redirect to quiz for functions topic
      if (currentTopic === "functions") {
        setTimeout(() => {
          window.location.href = "/quiz/functions";
        }, 1000);
      }
    }
  }

  // Show notification when video is completed
  function showVideoCompletionNotification() {
    // You can customize this notification as needed
    if (typeof showNotification === "function") {
      showNotification(
        "Video completed! This counts toward quiz prerequisites.",
        "success"
      );
    }
  }

  // Load progress from server API
  function loadProgress() {
    const topicCards = document.querySelectorAll(
      ".topic-card[data-subtopic]"
    );
    if (!topicCards.length) {
      return;
    }

    const subjectSlug = document.body?.dataset?.subject || null;

    topicCards.forEach((card) => {
      const subtopicId = card.dataset.subtopic;
      const subjectForCard = card.dataset.subject || subjectSlug;

      if (!subtopicId || !subjectForCard) {
        return;
      }

      fetch(`/api/progress/check/${subjectForCard}/${subtopicId}`)
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          if (data) {
            updateProgressBar(subtopicId, data);
          }
        })
        .catch((error) =>
          console.error(
            `Error loading progress for ${subtopicId}:`,
            error
          )
        );
    });
  }

  // Open video modal with selected topic
  function openVideo(topic) {
    currentTopic = topic;

    // VIDEO FEATURE DISABLED (temporary). Keeping original implementation
    // commented out below so it can be restored later.
    return;

    /*
    // Determine the correct API endpoint based on page context
    let apiUrl;
    const currentPath = window.location.pathname;
    let subjectForProgress = null;
    let subtopicForProgress = topic;

    if (currentPath.startsWith("/subjects/")) {
      // We're on a subject page, extract subject from URL
      const pathParts = currentPath.split("/");
      const subject = pathParts[2]; // /subjects/{subject}
      const subtopic = topic; // The topic is actually the subtopic ID
      subjectForProgress = subject;
      subtopicForProgress = subtopic;

      // For subject pages, we need to get the first video from the subtopic
      // The API expects /api/video/{subject}/{subtopic}/{videoKey}
      // We'll fetch the video data to get the available video keys
      apiUrl = `/api/video/${subject}/${subtopic}/${subtopic}`; // Assuming video key matches subtopic
    } else {
      // Legacy behavior for results page
      apiUrl = `/api/video/${topic}`;
    }

    // Get video data from API
    fetch(apiUrl)
      .then((response) => response.json())
      .then((data) => {
        // Set video title
        videoTitle.textContent = data.title;

        // Extract video ID from YouTube URL
        const videoId = extractVideoId(data.url);
        currentVideoId = videoId;
        currentVideoKey =
          data.id || data.video_id || data.topic_key || topic || videoId;

        if (subjectForProgress) {
          recordVideoOpened({
            subject: subjectForProgress,
            subtopic: subtopicForProgress,
            videoId: currentVideoKey,
          });
        }

        if (videoId) {
          // Create YouTube player container if it doesn't exist
          if (!document.getElementById("youtube-player")) {
            videoIframe.outerHTML = '<div id="youtube-player"></div>';
          }

          // Initialize YouTube player with enhanced tracking
          setTimeout(() => {
            initializePlayer(videoId, "youtube-player");
          }, 100);
        } else {
          // Fallback to iframe for non-YouTube videos
          videoIframe.src = data.url;

          // Legacy handling for functions topic
          if (topic === "functions") {
            videoIframe.onload = function () {
              videoIframe.contentWindow.postMessage(
                JSON.stringify({ event: "listening" }),
                "*"
              );

              window.addEventListener("message", function onVideoEnd(event) {
                let data;
                try {
                  data =
                    typeof event.data === "string"
                      ? JSON.parse(event.data)
                      : event.data;
                } catch (e) {
                  return;
                }

                if (data.event === "onStateChange" && data.info === 0) {
                  // 0 = ended
                  window.removeEventListener("message", onVideoEnd);
                  window.location.href = "/quiz/functions";
                }
              });
            };
          }
        }

    // Show modal
    videoModal.style.display = "flex";
    videoModal.dataset.currentTopic = topic;

        // Add admin override button if user is admin
    if (isAdminOverride) {
          addAdminOverrideButton();
        }
      })
      .catch((error) => console.error("Error loading video data:", error));
  }

  // Extract YouTube video ID from various URL formats
  function extractVideoId(url) {
    const regExp =
      /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*/;
    const match = url.match(regExp);
    return match && match[2].length === 11 ? match[2] : null;
  }

  // Add admin override button to video modal
  function addAdminOverrideButton() {
    if (document.getElementById("admin-override-btn")) return;

    const overrideBtn = document.createElement("button");
    overrideBtn.id = "admin-override-btn";
    overrideBtn.textContent = "Admin: Mark Complete";
    overrideBtn.className = "admin-override-button";
    overrideBtn.style.cssText = `
      position: absolute;
      top: 10px;
      right: 50px;
      background: #dc3545;
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      z-index: 1001;
    `;

    overrideBtn.addEventListener("click", function () {
      handleVideoComplete();
      closeVideo();
    });

    videoModal.querySelector(".modal-content").appendChild(overrideBtn);
  }

  // Close video modal
  function closeVideo() {
    // Get current topic from modal attribute
    const topic = videoModal.dataset.currentTopic;

    // Stop YouTube player if it exists
    if (ytPlayer) {
      ytPlayer.stopVideo();
    }

    // Clear tracking intervals
    const trackingInterval = videoModal.dataset.trackingInterval;
    if (trackingInterval) {
      clearInterval(trackingInterval);
    }

    // Remove admin override button
    const overrideBtn = document.getElementById("admin-override-btn");
    if (overrideBtn) {
      overrideBtn.remove();
    }

    // Stop video playback
    videoIframe.src = "";
    videoModal.style.display = "none";
    stopTracking();

    // Reset current tracking variables
    currentTopic = null;
    currentVideoId = null;

    // Redirect to quiz page if topic is "functions"
    if (topic === "functions") {
      window.location.href = "/quiz/functions";
    }
    */
  }

  // Track video progress (simulation for demonstration)
  let trackingInterval;
  function startTracking(topic) {
    // Get current progress
    fetch("/api/progress")
      .then((response) => response.json())
      .then((data) => {
        let currentProgress = data[topic] || 0;
        const videoProgressBar = document.getElementById("video-progress-bar");

        // Update progress bar initially
        videoProgressBar.style.width = `${currentProgress}%`;

        // Clear any existing interval
        if (trackingInterval) {
          clearInterval(trackingInterval);
        }

        // Update progress every 3 seconds (simulating video playback)
        // In a real implementation, you would use the video's timeupdate event
        trackingInterval = setInterval(() => {
          if (currentProgress < 100) {
            currentProgress += 5; // Increase by 5% each interval
            if (currentProgress > 100) currentProgress = 100;

            // Update progress bar
            videoProgressBar.style.width = `${currentProgress}%`;

            // Save progress to server
            saveProgress(topic, currentProgress);

            // If completed, stop tracking
            if (currentProgress === 100) {
              clearInterval(trackingInterval);
            }
          }
        }, 3000);
      });
  }

  function stopTracking() {
    if (trackingInterval) {
      clearInterval(trackingInterval);
    }
  }

  // Update video progress during playback
  function updateVideoProgress(topic, progress) {
    const videoProgressBar = document.getElementById("video-progress-bar");
    if (videoProgressBar) {
      videoProgressBar.style.width = `${progress}%`;
    }

    // Save progress every 10% increment to avoid too many API calls
    if (Math.floor(progress) % 10 === 0) {
      saveProgress(topic, progress);
    }
  }

  // Save progress to server
  function saveProgress(topic, progress) {
    updateProgressBar(topic, progress);
  }

  // Update topic progress bar and completion badge
  function updateProgressBar(topic, progress) {
    const progressBar = document.getElementById(`${topic}-progress`);
    const completionBadge = document.getElementById(`${topic}-badge`);

    if (progressBar) {
      const progressContainer = progressBar.closest(".progress-container");
      const srText = document.getElementById(`${topic}-progress-text`);
      const topicCard = progressBar.closest(".topic-card");

      const lessonTotal = Number(topicCard?.dataset?.lessonCount || 0);
      const videoTotal = Number(topicCard?.dataset?.videoCount || 0);
      const totalItemsAttr = Number(topicCard?.dataset?.totalCount || 0);
      const totalItems = totalItemsAttr || lessonTotal + videoTotal;

      let numericProgress = 0;
      let completedLessons = 0;
      let completedVideos = 0;
      let statsLessonTotal = lessonTotal;
      let statsVideoTotal = videoTotal;

      if (typeof progress === "number") {
        numericProgress = progress;
      } else if (progress && typeof progress === "object") {
        const lessons = progress.lessons || progress.lesson_stats || {};
        const videos = progress.videos || progress.video_stats || {};
        const overall = progress.overall || {};

        if (typeof lessons.total_count === "number") {
          statsLessonTotal = lessons.total_count;
        }
        if (typeof videos.total_count === "number") {
          statsVideoTotal = videos.total_count;
        }

        if (typeof lessons.completed_count === "number") {
          completedLessons = lessons.completed_count;
        } else if (Array.isArray(lessons.completed_lessons)) {
          completedLessons = lessons.completed_lessons.length;
        } else if (typeof lessons.completed === "number") {
          completedLessons = lessons.completed;
        }

        if (typeof videos.watched_count === "number") {
          completedVideos = videos.watched_count;
        } else if (Array.isArray(videos.watched_videos)) {
          completedVideos = videos.watched_videos.length;
        } else if (typeof videos.completed_count === "number") {
          completedVideos = videos.completed_count;
        }

        if (typeof overall.completion_percentage === "number") {
          numericProgress = overall.completion_percentage;
        } else if (typeof progress.completion_percentage === "number") {
          numericProgress = progress.completion_percentage;
        }
      }

      const derivedLessonTotal = Number.isFinite(statsLessonTotal)
        ? statsLessonTotal
        : lessonTotal;
      const derivedVideoTotal = Number.isFinite(statsVideoTotal)
        ? statsVideoTotal
        : videoTotal;
      const totalFromStats = derivedLessonTotal + derivedVideoTotal;
      const completedItems = completedLessons + completedVideos;

      if (!Number.isFinite(numericProgress)) {
        numericProgress = 0;
      }

      if (numericProgress === 0 && totalFromStats > 0) {
        numericProgress = (completedItems / totalFromStats) * 100;
      }

      numericProgress = Math.max(0, Math.min(100, numericProgress));

      progressBar.style.width = `${numericProgress}%`;
      progressBar.setAttribute("aria-valuenow", numericProgress.toString());

      if (progressContainer) {
        if (totalItems <= 0 && totalFromStats <= 0) {
          progressContainer.classList.add("is-hidden");
          progressContainer.setAttribute("aria-hidden", "true");
        } else {
          progressContainer.classList.remove("is-hidden");
          progressContainer.setAttribute("aria-hidden", "false");
        }
      }

      const descriptorParts = [];
      if (derivedLessonTotal > 0 || lessonTotal > 0) {
        descriptorParts.push("lessons");
      }
      if (derivedVideoTotal > 0 || videoTotal > 0) {
        descriptorParts.push("videos");
      }

      const descriptor =
        descriptorParts.length > 1
          ? "lessons and videos"
          : descriptorParts[0] || "content";
      const rounded = Math.round(numericProgress);
      const statusText =
        rounded >= 100
          ? `All ${descriptor} complete`
          : `${descriptor.charAt(0).toUpperCase() + descriptor.slice(1)} ${rounded}% complete`;
      progressBar.setAttribute("aria-valuetext", statusText);

      if (srText) {
        const lessonSummary =
          derivedLessonTotal > 0
            ? `${completedLessons} of ${derivedLessonTotal} lessons`
            : null;
        const videoSummary =
          derivedVideoTotal > 0
            ? `${completedVideos} of ${derivedVideoTotal} videos`
            : null;
        const summaries = [lessonSummary, videoSummary].filter(Boolean);
        const detailText = summaries.length
          ? `${summaries.join(" and ")} complete.`
          : "No learning items completed yet.";
        srText.textContent = `Progress update: ${detailText} Overall status: ${statusText}.`;
      }

      if (numericProgress === 100) {
        progressBar.classList.add("is-complete");
        if (completionBadge) {
          completionBadge.style.display = "inline";
        }
      } else {
        progressBar.classList.remove("is-complete");
      }

      if (topicCard) {
        topicCard.dataset.progress = numericProgress.toString();
        topicCard.dataset.completedLessons = completedLessons.toString();
        topicCard.dataset.completedVideos = completedVideos.toString();
      }
    }
  }

  window.updateProgressBar = updateProgressBar;
  window.loadProgress = loadProgress;
});
