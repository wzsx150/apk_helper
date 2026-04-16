// ApkHelperContextMenu.cpp - Windows 11 Context Menu Handler for APK files
// Optimized implementation with registry-based configuration

#include <shlobj.h>
#include <shlwapi.h>
#include <strsafe.h>
#include <new>
#include "ApkHelperContextMenu.h"

// Constructor
CApkHelperContextMenu::CApkHelperContextMenu() 
    : m_cRef(1)
    , m_spSite(nullptr)
    , m_bConfigLoaded(false)
    , m_bValidConfig(false)
{
    m_szExePath[0] = L'\0';
    m_szMenuTitle[0] = L'\0';
    DllAddRef();
}

// Destructor
CApkHelperContextMenu::~CApkHelperContextMenu()
{
    if (m_spSite)
    {
        m_spSite->Release();
        m_spSite = nullptr;
    }
    DllRelease();
}

// Load configuration from registry
void CApkHelperContextMenu::LoadConfig()
{
    if (m_bConfigLoaded)
    {
        return;
    }
    
    m_bConfigLoaded = true;
    m_bValidConfig = false;
    m_szExePath[0] = L'\0';
    
    // Set default menu title
    StringCchCopyW(m_szMenuTitle, ARRAYSIZE(m_szMenuTitle), DEFAULT_MENU_TITLE);
    
    HKEY hKey = nullptr;
    
    // Try to open registry key (try both 64-bit and 32-bit views)
    LONG lResult = RegOpenKeyExW(HKEY_CLASSES_ROOT, REG_KEY_PATH, 0, KEY_READ | KEY_WOW64_64KEY, &hKey);
    if (lResult != ERROR_SUCCESS)
    {
        lResult = RegOpenKeyExW(HKEY_CLASSES_ROOT, REG_KEY_PATH, 0, KEY_READ | KEY_WOW64_32KEY, &hKey);
    }
    
    if (lResult != ERROR_SUCCESS)
    {
        return;
    }
    
    // Read exe path
    DWORD dwSize = sizeof(m_szExePath);
    DWORD dwType = 0;
    lResult = RegQueryValueExW(hKey, REG_VALUE_EXEPATH, nullptr, &dwType, (LPBYTE)m_szExePath, &dwSize);
    
    if (lResult == ERROR_SUCCESS && (dwType == REG_SZ || dwType == REG_EXPAND_SZ))
    {
        // Expand environment variables if needed
        if (dwType == REG_EXPAND_SZ)
        {
            WCHAR szExpanded[MAX_PATH] = {0};
            if (ExpandEnvironmentStringsW(m_szExePath, szExpanded, ARRAYSIZE(szExpanded)) > 0)
            {
                StringCchCopyW(m_szExePath, ARRAYSIZE(m_szExePath), szExpanded);
            }
        }
        
        // Validate exe path
        m_bValidConfig = IsExePathValid();
    }
    
    // Read menu title (default value)
    WCHAR szTitle[256] = {0};
    dwSize = sizeof(szTitle);
    lResult = RegQueryValueExW(hKey, nullptr, nullptr, &dwType, (LPBYTE)szTitle, &dwSize);
    
    if (lResult == ERROR_SUCCESS && dwType == REG_SZ && szTitle[0] != L'\0')
    {
        StringCchCopyW(m_szMenuTitle, ARRAYSIZE(m_szMenuTitle), szTitle);
    }
    
    RegCloseKey(hKey);
}

// Check if exe path is valid
bool CApkHelperContextMenu::IsExePathValid() const
{
    if (m_szExePath[0] == L'\0')
    {
        return false;
    }
    
    // Check if file exists
    DWORD dwAttrib = GetFileAttributesW(m_szExePath);
    return (dwAttrib != INVALID_FILE_ATTRIBUTES && !(dwAttrib & FILE_ATTRIBUTE_DIRECTORY));
}

// IUnknown::QueryInterface
IFACEMETHODIMP CApkHelperContextMenu::QueryInterface(REFIID riid, void **ppv)
{
    if (ppv == nullptr)
    {
        return E_POINTER;
    }

    *ppv = nullptr;

    if (riid == __uuidof(IUnknown) ||
        riid == __uuidof(IExplorerCommand))
    {
        *ppv = static_cast<IExplorerCommand *>(this);
    }
    else if (riid == __uuidof(IObjectWithSite))
    {
        *ppv = static_cast<IObjectWithSite *>(this);
    }
    else
    {
        return E_NOINTERFACE;
    }

    AddRef();
    return S_OK;
}

// IUnknown::AddRef
IFACEMETHODIMP_(ULONG) CApkHelperContextMenu::AddRef()
{
    return InterlockedIncrement(&m_cRef);
}

// IUnknown::Release
IFACEMETHODIMP_(ULONG) CApkHelperContextMenu::Release()
{
    LONG cRef = InterlockedDecrement(&m_cRef);
    if (cRef == 0)
    {
        delete this;
    }
    return (ULONG)cRef;
}

// IExplorerCommand::GetTitle
IFACEMETHODIMP CApkHelperContextMenu::GetTitle(IShellItemArray *psiItemArray, LPWSTR *ppszName)
{
    if (ppszName == nullptr)
    {
        return E_POINTER;
    }

    *ppszName = nullptr;
    
    __try
    {
        LoadConfig();
        
        size_t cchLen = 0;
        HRESULT hr = StringCchLengthW(m_szMenuTitle, ARRAYSIZE(m_szMenuTitle), &cchLen);
        if (FAILED(hr) || cchLen == 0)
        {
            StringCchLengthW(DEFAULT_MENU_TITLE, 256, &cchLen);
        }
        
        LPWSTR pszResult = (LPWSTR)CoTaskMemAlloc((cchLen + 1) * sizeof(WCHAR));
        if (pszResult == nullptr)
        {
            return E_OUTOFMEMORY;
        }
        
        if (m_szMenuTitle[0] != L'\0')
        {
            StringCchCopyW(pszResult, cchLen + 1, m_szMenuTitle);
        }
        else
        {
            StringCchCopyW(pszResult, cchLen + 1, DEFAULT_MENU_TITLE);
        }
        
        *ppszName = pszResult;
        return S_OK;
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        return E_FAIL;
    }
}

// IExplorerCommand::GetIcon
IFACEMETHODIMP CApkHelperContextMenu::GetIcon(IShellItemArray *psiItemArray, LPWSTR *ppszIcon)
{
    if (ppszIcon == nullptr)
    {
        return E_POINTER;
    }
    
    *ppszIcon = nullptr;
    
    __try
    {
        LoadConfig();
        
        // Use the exe's icon if valid
        if (m_bValidConfig && m_szExePath[0] != L'\0')
        {
            size_t cchLen = 0;
            HRESULT hr = StringCchLengthW(m_szExePath, MAX_PATH, &cchLen);
            if (SUCCEEDED(hr))
            {
                // Format: "path_to_exe,0" (use first icon from exe)
                LPWSTR pszResult = (LPWSTR)CoTaskMemAlloc((cchLen + 4) * sizeof(WCHAR));
                if (pszResult != nullptr)
                {
                    StringCchCopyW(pszResult, cchLen + 4, m_szExePath);
                    StringCchCatW(pszResult, cchLen + 4, L",0");
                    *ppszIcon = pszResult;
                    return S_OK;
                }
            }
        }
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        // Ignore exceptions
    }
    
    return E_NOTIMPL;
}

// IExplorerCommand::GetToolTip
IFACEMETHODIMP CApkHelperContextMenu::GetToolTip(IShellItemArray *psiItemArray, LPWSTR *ppszInfotip)
{
    if (ppszInfotip == nullptr)
    {
        return E_POINTER;
    }
    *ppszInfotip = nullptr;
    return E_NOTIMPL;
}

// IExplorerCommand::GetCanonicalName
IFACEMETHODIMP CApkHelperContextMenu::GetCanonicalName(GUID *pguidCommandName)
{
    if (pguidCommandName == nullptr)
    {
        return E_POINTER;
    }
    *pguidCommandName = CLSID_ApkHelperContextMenu;
    return S_OK;
}

// IExplorerCommand::GetState
IFACEMETHODIMP CApkHelperContextMenu::GetState(IShellItemArray *psiItemArray, BOOL fOkToBeSlow, EXPCMDSTATE *pCmdState)
{
    if (pCmdState == nullptr)
    {
        return E_POINTER;
    }
    
    // Load config and check if we should show the menu
    LoadConfig();
    
    if (!m_bValidConfig)
    {
        *pCmdState = ECS_HIDDEN;
    }
    else
    {
        *pCmdState = ECS_ENABLED;
    }
    
    return S_OK;
}

// IExplorerCommand::Invoke
IFACEMETHODIMP CApkHelperContextMenu::Invoke(IShellItemArray *psiItemArray, IBindCtx *pbc)
{
    __try
    {
        if (psiItemArray == nullptr)
        {
            return S_OK;
        }
        
        LoadConfig();
        
        if (!m_bValidConfig)
        {
            return S_OK;
        }
        
        DWORD dwCount = 0;
        HRESULT hr = psiItemArray->GetCount(&dwCount);
        if (FAILED(hr) || dwCount == 0)
        {
            return S_OK;
        }
        
        // 检查选中文件数量是否超过最大限制
        if (dwCount > MAX_SELECTED_FILES)
        {
            // 构建提示消息：告知用户当前选中数量和最大允许数量
            WCHAR szMsg[512] = {0};
            StringCchPrintfW(szMsg, ARRAYSIZE(szMsg),
                L"您选中了 %u 个文件，最多支持同时打开 %u 个文件。\n\n请减少选中的文件数量后重试。",
                dwCount, MAX_SELECTED_FILES);
            MessageBoxW(nullptr, szMsg, L"APK Helper", MB_OK | MB_ICONINFORMATION);
            return S_OK;
        }
        
        // Process each selected file
        for (DWORD i = 0; i < dwCount; i++)
        {
            IShellItem *psi = nullptr;
            hr = psiItemArray->GetItemAt(i, &psi);
            if (FAILED(hr) || psi == nullptr)
            {
                continue;
            }
            
            LPWSTR pszFilePath = nullptr;
            hr = psi->GetDisplayName(SIGDN_FILESYSPATH, &pszFilePath);
            if (SUCCEEDED(hr) && pszFilePath != nullptr)
            {
                // Build command line
                WCHAR szCmdLine[MAX_CMD_LINE] = {0};
                StringCchCopyW(szCmdLine, ARRAYSIZE(szCmdLine), L"\"");
                StringCchCatW(szCmdLine, ARRAYSIZE(szCmdLine), m_szExePath);
                StringCchCatW(szCmdLine, ARRAYSIZE(szCmdLine), L"\" \"");
                StringCchCatW(szCmdLine, ARRAYSIZE(szCmdLine), pszFilePath);
                StringCchCatW(szCmdLine, ARRAYSIZE(szCmdLine), L"\"");
                
                // Launch process
                STARTUPINFOW si = { sizeof(si) };
                si.dwFlags = STARTF_USESHOWWINDOW;
                si.wShowWindow = SW_SHOWNORMAL;
                PROCESS_INFORMATION pi = {0};
                
                BOOL bResult = CreateProcessW(
                    nullptr,
                    szCmdLine,
                    nullptr,
                    nullptr,
                    FALSE,
                    CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT,
                    nullptr,
                    nullptr,
                    &si,
                    &pi);
                
                if (bResult)
                {
                    CloseHandle(pi.hProcess);
                    CloseHandle(pi.hThread);
                }
                
                CoTaskMemFree(pszFilePath);
            }
            
            psi->Release();
        }
        
        return S_OK;
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        return S_OK;
    }
}

// IExplorerCommand::GetFlags
IFACEMETHODIMP CApkHelperContextMenu::GetFlags(EXPCMDFLAGS *pFlags)
{
    if (pFlags == nullptr)
    {
        return E_POINTER;
    }
    *pFlags = ECF_DEFAULT;
    return S_OK;
}

// IExplorerCommand::EnumSubCommands
IFACEMETHODIMP CApkHelperContextMenu::EnumSubCommands(IEnumExplorerCommand **ppEnum)
{
    if (ppEnum == nullptr)
    {
        return E_POINTER;
    }
    *ppEnum = nullptr;
    return E_NOTIMPL;
}

// IObjectWithSite::SetSite
IFACEMETHODIMP CApkHelperContextMenu::SetSite(IUnknown *pUnkSite)
{
    if (m_spSite)
    {
        m_spSite->Release();
        m_spSite = nullptr;
    }
    
    m_spSite = pUnkSite;
    if (m_spSite)
    {
        m_spSite->AddRef();
    }
    
    // Reset config cache when site changes
    m_bConfigLoaded = false;
    
    return S_OK;
}

// IObjectWithSite::GetSite
IFACEMETHODIMP CApkHelperContextMenu::GetSite(REFIID riid, void **ppv)
{
    if (ppv == nullptr)
    {
        return E_POINTER;
    }

    *ppv = nullptr;
    
    if (m_spSite)
    {
        return m_spSite->QueryInterface(riid, ppv);
    }
    
    return E_FAIL;
}
