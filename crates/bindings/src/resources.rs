//! 应用与窗口代次拥有的可清空回调、监听器和待执行任务。
use crate::{binding_error, runtime::RuntimeState, window_state::WindowState};
use pyo3::prelude::*;
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex, Weak,
    },
};
use tauri::Listener;

pub struct CallbackSlot {
    pub owner: Option<Arc<WindowState>>,
    callback: Mutex<Option<Py<PyAny>>>,
}
impl CallbackSlot {
    pub fn new(owner: Option<Arc<WindowState>>, callback: Py<PyAny>) -> Arc<Self> {
        Arc::new(Self {
            owner,
            callback: Mutex::new(Some(callback)),
        })
    }
    pub fn check_owner(&self) -> PyResult<()> {
        self.owner
            .as_ref()
            .map_or(Ok(()), |owner| owner.ensure_active())
    }
    pub fn callback(&self, py: Python<'_>, take: bool) -> PyResult<Option<Py<PyAny>>> {
        let mut slot = self
            .callback
            .lock()
            .map_err(|_| binding_error("state_failed", "Callback unavailable"))?;
        Ok(if take {
            slot.take()
        } else {
            slot.as_ref().map(|callback| callback.clone_ref(py))
        })
    }
    pub fn present(&self) -> bool {
        self.callback.lock().is_ok_and(|slot| slot.is_some())
    }
    pub fn clear(&self) {
        let callback = self.callback.lock().ok().and_then(|mut slot| slot.take());
        drop(callback);
    }
    fn belongs_to(&self, owner: &Arc<WindowState>) -> bool {
        self.owner
            .as_ref()
            .is_some_and(|current| Arc::ptr_eq(current, owner))
    }
}

#[derive(Default)]
struct Registry {
    channels: Vec<Weak<crate::channel::ChannelState>>,
    #[cfg(all(feature = "plugin-dialog", desktop))]
    operations: HashMap<u64, Arc<crate::dialog::Operation>>,
    listeners: HashMap<u32, Arc<CallbackSlot>>,
    tasks: HashMap<u64, Arc<CallbackSlot>>,
    #[cfg(desktop)]
    menus: Vec<Arc<CallbackSlot>>,
}
#[derive(Default)]
pub struct Resources {
    registry: Mutex<Registry>,
    next_task: AtomicU64,
}
impl Resources {
    #[cfg(desktop)]
    pub fn add_menu(&self, runtime: &RuntimeState, slot: &Arc<CallbackSlot>) -> PyResult<()> {
        runtime.ensure_active()?;
        slot.check_owner()?;
        if slot.owner.is_some() {
            self.clear_menu(slot.owner.as_ref())?;
        }
        self.registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?
            .menus
            .push(Arc::clone(slot));
        Ok(())
    }
    #[cfg(desktop)]
    pub fn clear_menu(&self, owner: Option<&Arc<WindowState>>) -> PyResult<()> {
        let mut removed = Vec::new();
        self.registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?
            .menus
            .retain(|slot| {
                let matches = match owner {
                    Some(owner) => slot.belongs_to(owner),
                    None => slot.owner.is_none(),
                };
                if matches {
                    removed.push(Arc::clone(slot));
                }
                !matches
            });
        for slot in removed {
            slot.clear();
        }
        Ok(())
    }
    pub fn add_channel(
        &self,
        runtime: &RuntimeState,
        state: &Arc<crate::channel::ChannelState>,
    ) -> PyResult<()> {
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?;
        runtime.ensure_active()?;
        state.owner.ensure_active()?;
        registry.channels.retain(|entry| entry.strong_count() > 0);
        registry.channels.push(Arc::downgrade(state));
        Ok(())
    }
    /// 按编号与来源窗口查找通道；归属不符时不归还其他窗口的配额。
    pub fn channel(
        &self,
        id: u32,
        owner: &Arc<WindowState>,
    ) -> Option<Arc<crate::channel::ChannelState>> {
        let mut registry = self.registry.lock().ok()?;
        registry.channels.retain(|entry| entry.strong_count() > 0);
        registry
            .channels
            .iter()
            .filter_map(Weak::upgrade)
            .find(|state| state.id == id && state.belongs_to(owner))
    }
    #[cfg(all(feature = "plugin-dialog", desktop))]
    // 保持 MSRV 1.90：替代方法 try_update 需要 1.95，升级 MSRV 后再切换。
    #[allow(deprecated)]
    pub fn add_operation(
        &self,
        runtime: &RuntimeState,
        operation: &Arc<crate::dialog::Operation>,
    ) -> PyResult<u64> {
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?;
        runtime.ensure_active()?;
        operation.check_owner()?;
        let id = self
            .next_task
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |id| id.checked_add(1))
            .map_err(|_| binding_error("state_failed", "Task identifiers exhausted"))?;
        registry.operations.insert(id, Arc::clone(operation));
        Ok(id)
    }
    #[cfg(all(feature = "plugin-dialog", desktop))]
    pub fn operation(&self, id: u64) -> Option<Arc<crate::dialog::Operation>> {
        self.registry
            .lock()
            .ok()
            .and_then(|registry| registry.operations.get(&id).cloned())
    }
    #[cfg(all(feature = "plugin-dialog", desktop))]
    pub fn take_operation(&self, id: u64) -> Option<Arc<crate::dialog::Operation>> {
        self.registry
            .lock()
            .ok()
            .and_then(|mut registry| registry.operations.remove(&id))
    }
    pub fn add_listener(
        &self,
        runtime: &RuntimeState,
        id: u32,
        slot: &Arc<CallbackSlot>,
    ) -> PyResult<()> {
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?;
        runtime.ensure_active()?;
        slot.check_owner()?;
        if slot.present() {
            registry.listeners.insert(id, Arc::clone(slot));
        }
        Ok(())
    }
    pub fn remove_listener(
        &self,
        id: u32,
        owner: Option<&Arc<WindowState>>,
    ) -> PyResult<Option<Arc<CallbackSlot>>> {
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?;
        if let (Some(owner), Some(slot)) = (owner, registry.listeners.get(&id)) {
            if !slot.belongs_to(owner) {
                return Err(binding_error(
                    "listener_owner",
                    "Listener belongs to a different resource",
                ));
            }
        }
        Ok(registry.listeners.remove(&id))
    }
    // 保持 MSRV 1.90：替代方法 try_update 需要 1.95，升级 MSRV 后再切换。
    #[allow(deprecated)]
    pub fn add_task(&self, runtime: &RuntimeState, slot: &Arc<CallbackSlot>) -> PyResult<u64> {
        let mut registry = self
            .registry
            .lock()
            .map_err(|_| binding_error("state_failed", "Resources unavailable"))?;
        runtime.ensure_active()?;
        slot.check_owner()?;
        let id = self
            .next_task
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |id| id.checked_add(1))
            .map_err(|_| binding_error("state_failed", "Task identifiers exhausted"))?;
        registry.tasks.insert(id, Arc::clone(slot));
        Ok(id)
    }
    pub fn take_task(&self, id: u64) -> Option<Arc<CallbackSlot>> {
        self.registry
            .lock()
            .ok()
            .and_then(|mut registry| registry.tasks.remove(&id))
    }
    pub fn clear(&self, handle: &tauri::AppHandle, owner: Option<&Arc<WindowState>>) {
        #[cfg(desktop)]
        {
            let mut removed = Vec::new();
            if let Ok(mut registry) = self.registry.lock() {
                registry.menus.retain(|slot| {
                    let matches = owner.is_none_or(|owner| slot.belongs_to(owner));
                    if matches {
                        removed.push(Arc::clone(slot));
                    }
                    !matches
                });
            }
            for slot in removed {
                slot.clear();
            }
        }
        let mut channels = Vec::new();
        if let Ok(mut registry) = self.registry.lock() {
            registry.channels.retain(|entry| {
                let Some(state) = entry.upgrade() else {
                    return false;
                };
                if owner.is_none_or(|owner| state.belongs_to(owner)) {
                    channels.push(state);
                    false
                } else {
                    true
                }
            });
        }
        for state in channels {
            state.clear();
        }
        #[cfg(all(feature = "plugin-dialog", desktop))]
        let operations = self
            .registry
            .lock()
            .map(|mut registry| {
                let ids = registry
                    .operations
                    .iter()
                    .filter_map(|(id, operation)| {
                        owner
                            .is_none_or(|owner| operation.belongs_to(owner))
                            .then_some(*id)
                    })
                    .collect::<Vec<_>>();
                ids.into_iter()
                    .filter_map(|id| registry.operations.remove(&id))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        #[cfg(all(feature = "plugin-dialog", desktop))]
        for operation in operations {
            operation.cancel(if owner.is_some() {
                "window_closed"
            } else {
                "app_closed"
            });
        }
        let removed = if let Ok(mut registry) = self.registry.lock() {
            let listener_ids = registry
                .listeners
                .iter()
                .filter_map(|(id, slot)| {
                    owner
                        .is_none_or(|owner| slot.belongs_to(owner))
                        .then_some(*id)
                })
                .collect::<Vec<_>>();
            let task_ids = registry
                .tasks
                .iter()
                .filter_map(|(id, slot)| {
                    owner
                        .is_none_or(|owner| slot.belongs_to(owner))
                        .then_some(*id)
                })
                .collect::<Vec<_>>();
            let listeners = listener_ids
                .into_iter()
                .filter_map(|id| registry.listeners.remove(&id).map(|slot| (id, slot)))
                .collect::<Vec<_>>();
            let tasks = task_ids
                .into_iter()
                .filter_map(|id| registry.tasks.remove(&id))
                .collect::<Vec<_>>();
            (listeners, tasks)
        } else {
            return;
        };
        // 所有 native 注销与 Python 析构均发生在注册表锁外。
        for (id, slot) in removed.0 {
            slot.clear();
            handle.unlisten(id);
        }
        for slot in removed.1 {
            slot.clear();
        }
    }
}
