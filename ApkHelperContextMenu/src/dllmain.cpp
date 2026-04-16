// dllmain.cpp - DLL入口点和ClassFactory实现

#include <shlobj.h>
#include <shlwapi.h>
#include <strsafe.h>
#include <new>
#include "ApkHelperContextMenu.h"

HINSTANCE g_hInst = nullptr;
long g_cRef = 0;

// DLL入口点
STDAPI_(BOOL) DllMain(HINSTANCE hInstance, DWORD dwReason, void *)
{
    if (dwReason == DLL_PROCESS_ATTACH)
    {
        g_hInst = hInstance;
        DisableThreadLibraryCalls(hInstance);
    }
    return TRUE;
}

// 增加全局引用计数
STDAPI_(void) DllAddRef()
{
    InterlockedIncrement(&g_cRef);
}

// 减少全局引用计数
STDAPI_(void) DllRelease()
{
    InterlockedDecrement(&g_cRef);
}

// 检查DLL是否可以卸载
STDAPI DllCanUnloadNow()
{
    return (g_cRef == 0) ? S_OK : S_FALSE;
}

// ClassFactory实现
class CClassFactory : public IClassFactory
{
public:
    CClassFactory() : m_cRef(1)
    {
        DllAddRef();
    }

    virtual ~CClassFactory()
    {
        DllRelease();
    }

    // IUnknown::QueryInterface
    IFACEMETHODIMP QueryInterface(REFIID riid, void **ppv) override
    {
        if (ppv == nullptr)
        {
            return E_POINTER;
        }

        *ppv = nullptr;

        if (riid == __uuidof(IUnknown) ||
            riid == __uuidof(IClassFactory))
        {
            *ppv = static_cast<IClassFactory *>(this);
            AddRef();
            return S_OK;
        }

        return E_NOINTERFACE;
    }

    // IUnknown::AddRef
    IFACEMETHODIMP_(ULONG) AddRef() override
    {
        return InterlockedIncrement(&m_cRef);
    }

    // IUnknown::Release
    IFACEMETHODIMP_(ULONG) Release() override
    {
        LONG cRef = InterlockedDecrement(&m_cRef);
        if (cRef == 0)
        {
            delete this;
        }
        return (ULONG)cRef;
    }

    // IClassFactory::CreateInstance
    IFACEMETHODIMP CreateInstance(IUnknown *pUnkOuter, REFIID riid, void **ppv) override
    {
        if (ppv == nullptr)
        {
            return E_POINTER;
        }

        *ppv = nullptr;

        // 不支持聚合
        if (pUnkOuter != nullptr)
        {
            return CLASS_E_NOAGGREGATION;
        }

        // 创建对象实例
        CApkHelperContextMenu *pObj = new (std::nothrow) CApkHelperContextMenu();
        if (pObj == nullptr)
        {
            return E_OUTOFMEMORY;
        }

        HRESULT hr = pObj->QueryInterface(riid, ppv);
        pObj->Release();

        return hr;
    }

    // IClassFactory::LockServer
    IFACEMETHODIMP LockServer(BOOL fLock) override
    {
        if (fLock)
        {
            DllAddRef();
        }
        else
        {
            DllRelease();
        }
        return S_OK;
    }

private:
    long m_cRef;
};

// 获取类工厂
STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void **ppv)
{
    if (ppv == nullptr)
    {
        return E_POINTER;
    }

    *ppv = nullptr;

    // 检查CLSID是否匹配
    if (rclsid != CLSID_ApkHelperContextMenu)
    {
        return CLASS_E_CLASSNOTAVAILABLE;
    }

    // 创建类工厂
    CClassFactory *pFactory = new (std::nothrow) CClassFactory();
    if (pFactory == nullptr)
    {
        return E_OUTOFMEMORY;
    }

    HRESULT hr = pFactory->QueryInterface(riid, ppv);
    pFactory->Release();

    return hr;
}

// 注册服务器（Sparse Package不需要此函数，但保留以兼容）
STDAPI DllRegisterServer()
{
    return S_OK;
}

// 注销服务器（Sparse Package不需要此函数，但保留以兼容）
STDAPI DllUnregisterServer()
{
    return S_OK;
}
