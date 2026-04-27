using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// 验证项目清理工具。
/// 当运行时脚本被替换或复制过程中丢失 .meta 时，能快速清掉场景中的 Missing Script 引用。
/// </summary>
public static class AudioForgeMissingScriptCleaner
{
    [MenuItem("AudioForge/Cleanup/Remove Missing Scripts In Selection")]
    public static void RemoveMissingScriptsInSelection()
    {
        GameObject[] selection = Selection.gameObjects;
        if (selection == null || selection.Length == 0)
        {
            Debug.LogWarning("AudioForge: no GameObject selected.");
            return;
        }

        int removedCount = 0;
        for (int index = 0; index < selection.Length; index += 1)
        {
            removedCount += RemoveMissingScriptsRecursive(selection[index]);
        }

        if (removedCount > 0)
        {
            EditorSceneManager.MarkSceneDirty(SceneManager.GetActiveScene());
        }

        Debug.Log("AudioForge: removed " + removedCount + " missing script reference(s) from selection.");
    }

    [MenuItem("AudioForge/Cleanup/Remove Missing Scripts In Active Scene")]
    public static void RemoveMissingScriptsInActiveScene()
    {
        Scene activeScene = SceneManager.GetActiveScene();
        if (!activeScene.IsValid())
        {
            Debug.LogWarning("AudioForge: active scene is invalid.");
            return;
        }

        GameObject[] roots = activeScene.GetRootGameObjects();
        int removedCount = 0;
        for (int index = 0; index < roots.Length; index += 1)
        {
            removedCount += RemoveMissingScriptsRecursive(roots[index]);
        }

        if (removedCount > 0)
        {
            EditorSceneManager.MarkSceneDirty(activeScene);
        }

        Debug.Log("AudioForge: removed " + removedCount + " missing script reference(s) from active scene.");
    }

    private static int RemoveMissingScriptsRecursive(GameObject root)
    {
        int removedCount = GameObjectUtility.RemoveMonoBehavioursWithMissingScript(root);
        Transform transform = root.transform;
        for (int index = 0; index < transform.childCount; index += 1)
        {
            removedCount += RemoveMissingScriptsRecursive(transform.GetChild(index).gameObject);
        }

        return removedCount;
    }
}