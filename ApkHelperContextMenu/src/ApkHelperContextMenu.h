#pragma once

#include <shlobj.h>
#include <shlwapi.h>
#include <new>

// {D852287C-EAB7-4D17-AF41-33120B7A8D1A}
static const GUID CLSID_ApkHelperContextMenu =
{ 0xD852287C, 0xEAB7, 0x4D17, { 0xAF, 0x41, 0x33, 0x12, 0x0B, 0x7A, 0x8D, 0x1A } };

// 注册表路径常量
static const WCHAR* REG_KEY_PATH = L"SystemFileAssociations\\.apk\\APKHelperEx";
static const WCHAR* REG_VALUE_EXEPATH = L"ApkHelper.exepath";
static const WCHAR* DEFAULT_MENU_TITLE = L"APK Helper";

// 最大路径长度
static const DWORD MAX_CMD_LINE = 8192;

// 右键菜单同时打开的最大文件数量限制
// 防止用户误选大量文件导致系统资源耗尽
static const DWORD MAX_SELECTED_FILES = 10;

#ifdef __cplusplus
extern "C" {
#endif

void DllAddRef();
void DllRelease();

#ifdef __cplusplus
}
#endif

class CApkHelperContextMenu : public IExplorerCommand, public IObjectWithSite
{
public:
    CApkHelperContextMenu();
    virtual ~CApkHelperContextMenu();

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void **ppv) override;
    IFACEMETHODIMP_(ULONG) AddRef() override;
    IFACEMETHODIMP_(ULONG) Release() override;

    // IExplorerCommand
    IFACEMETHODIMP GetTitle(IShellItemArray *psiItemArray, LPWSTR *ppszName) override;
    IFACEMETHODIMP GetIcon(IShellItemArray *psiItemArray, LPWSTR *ppszIcon) override;
    IFACEMETHODIMP GetToolTip(IShellItemArray *psiItemArray, LPWSTR *ppszInfotip) override;
    IFACEMETHODIMP GetCanonicalName(GUID *pguidCommandName) override;
    IFACEMETHODIMP GetState(IShellItemArray *psiItemArray, BOOL fOkToBeSlow, EXPCMDSTATE *pCmdState) override;
    IFACEMETHODIMP Invoke(IShellItemArray *psiItemArray, IBindCtx *pbc) override;
    IFACEMETHODIMP GetFlags(EXPCMDFLAGS *pFlags) override;
    IFACEMETHODIMP EnumSubCommands(IEnumExplorerCommand **ppEnum) override;

    // IObjectWithSite
    IFACEMETHODIMP SetSite(IUnknown *pUnkSite) override;
    IFACEMETHODIMP GetSite(REFIID riid, void **ppv) override;

private:
    long m_cRef;
    IUnknown *m_spSite;
    
    // 缓存的配置
    WCHAR m_szExePath[MAX_PATH];
    WCHAR m_szMenuTitle[256];
    bool m_bConfigLoaded;
    bool m_bValidConfig;
    
    // 内部方法
    void LoadConfig();
    bool IsExePathValid() const;
};
