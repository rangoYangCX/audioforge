using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 轻量级运行时调试面板。
/// 目标不是做最终 UI，而是给 Unity 开发人员一个可直接观察事件/总线/活跃声部状态的参考入口。
/// </summary>
[AddComponentMenu("AudioForge/AudioForge Runtime Debug Panel")]
public sealed class AudioForgeRuntimeDebugPanel : MonoBehaviour
{
    public AudioForgeRuntime Runtime;
    public KeyCode ToggleKey = KeyCode.BackQuote;
    public bool Visible = true;
    public int MaxEventRecordsToShow = 12;
    public int MaxBusRecordsToShow = 8;

    private Vector2 _scrollPosition;

    private void Update()
    {
        if (ToggleKey != KeyCode.None && Input.GetKeyDown(ToggleKey))
        {
            Visible = !Visible;
        }
    }

    private void OnGUI()
    {
        if (!Visible)
        {
            return;
        }

        AudioForgeRuntime runtime = ResolveRuntime();
        GUILayout.BeginArea(new Rect(12f, 12f, 620f, 460f), "AudioForge Runtime Debug", GUI.skin.window);
        if (runtime == null)
        {
            GUILayout.Label("Runtime: null");
            GUILayout.EndArea();
            return;
        }

        GUILayout.Label("Ready: " + runtime.IsReady);
        GUILayout.Label("Events: " + runtime.GetRegisteredEventCount());
        GUILayout.Label("Buses: " + runtime.GetRegisteredBusCount());
        GUILayout.Label("Runtime Audio Format: " + runtime.GetRuntimeAudioFormat());
        GUILayout.Label("Resource Provider: " + runtime.GetResourceProviderName());
        GUILayout.Label("Reference Time Preserving Pitch: " + runtime.UseReferenceTimePreservingPitch);
        GUILayout.Label("Processed Clip Cache: " + runtime.GetProcessedClipCacheCount());

        _scrollPosition = GUILayout.BeginScrollView(_scrollPosition, GUILayout.Height(360f));
        GUILayout.Label("== Bus State ==");
        List<string> busNames = runtime.GetBusNames();
        for (int index = 0; index < busNames.Count; index += 1)
        {
            string busName = busNames[index];
            GUILayout.Label(string.Format("Bus {0} | Volume={1:0.00} | Muted={2}", busName, runtime.GetBusVolume(busName), runtime.IsBusMuted(busName)));
        }

        GUILayout.Space(8f);
        GUILayout.Label("== Event State ==");
        List<string> eventIds = runtime.GetEventIds();
        for (int index = 0; index < eventIds.Count; index += 1)
        {
            string eventId = eventIds[index];
            GUILayout.Label(string.Format("Event {0} | ActiveVoices={1}", eventId, runtime.GetActiveVoiceCount(eventId)));
        }

        GUILayout.Space(8f);
        GUILayout.Label("== Recent Event Records ==");
        List<AudioForgeDebugEventRecord> eventRecords = runtime.GetRecentDebugEventRecords();
        int eventRecordCount = Mathf.Min(MaxEventRecordsToShow, eventRecords.Count);
        for (int index = 0; index < eventRecordCount; index += 1)
        {
            AudioForgeDebugEventRecord record = eventRecords[index];
            GUILayout.Label(string.Format(
                "[{0:0.00}] {1} | {2} | Clip={3} | Pitch={4} | Combo={5} | Preserve={6} | CacheHit={7} | Trim={8}-{9} | Fade={10}/{11} | Loop={12}-{13} | {14}",
                record.Timestamp,
                record.EventId,
                record.Result,
                string.IsNullOrEmpty(record.ClipId) ? "-" : record.ClipId,
                record.PitchCents,
                record.ComboStep,
                record.UsedTimePreservingPitch,
                record.CacheHit,
                record.TrimStartMs,
                record.TrimEndMs,
                record.FadeInMs,
                record.FadeOutMs,
                record.LoopStartMs,
                record.LoopEndMs,
                record.Message));
        }

        GUILayout.Space(8f);
        GUILayout.Label("== Recent Bus Records ==");
        List<AudioForgeDebugBusRecord> busRecords = runtime.GetRecentDebugBusRecords();
        int busRecordCount = Mathf.Min(MaxBusRecordsToShow, busRecords.Count);
        for (int index = 0; index < busRecordCount; index += 1)
        {
            AudioForgeDebugBusRecord record = busRecords[index];
            GUILayout.Label(string.Format(
                "[{0:0.00}] {1} | {2} | Volume={3:0.00} | Muted={4}",
                record.Timestamp,
                record.BusName,
                record.Action,
                record.Volume,
                record.IsMuted));
        }
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    private AudioForgeRuntime ResolveRuntime()
    {
        if (Runtime != null)
        {
            return Runtime;
        }

        if (AudioForgeRuntime.Instance != null)
        {
            Runtime = AudioForgeRuntime.Instance;
            return Runtime;
        }

        Runtime = FindObjectOfType<AudioForgeRuntime>();
        return Runtime;
    }
}