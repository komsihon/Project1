/*
 * @license
 * ikwen (https://ikwen.com)
 * Copyright 2020 ikwen Ltd. All rights reserved.
 */
'use strict';

let deferredInstallPrompt = null;

const applicationServerPublicKey = 'BMOWBPPR-82V3c6O94a0vELezblmC58hUp5N92rrsBrH3x3MLxMRkf2S-Wx1sGxpbkQ8gOfQt01V5bnip9crb-Y';
const pwaOverlay = document.getElementById('pwa-overlay');

let isSubscribed = false;
let swRegistration = null;

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').then((reg) => {
            console.log('Service worker registered.', reg);
            swRegistration = reg;
            if ('PushManager' in window) {
                initializePushUI();
            } else {
                $('.push-promotion').hide();
            }
        });
    });
}

// Add click event to install
$('body').on('click', '.install-pwa:not(.processing)', installPWA)
    .on('click', '.install-promotion .close', revokeInstallAndRemember);

// CODELAB: Add event listener for beforeinstallprompt event
window.addEventListener('beforeinstallprompt', saveBeforeInstallPromptEvent);

/**
 * Event handler for beforeinstallprompt event.
 *   Saves the event & shows install button.
 *
 * @param {Event} evt
 */
function saveBeforeInstallPromptEvent(evt) {
  // CODELAB: Add code to save event & show the install button.
    deferredInstallPrompt = evt;
    console.log("Before install saved");
    $('.install-pwa').removeClass('disabled').show();
    $('.install-promotion').fadeIn();
    evt.preventDefault();
}


/**
 * Event handler for butInstall - Does the PWA installation.
 *
 * @param {Event} evt
 */
function installPWA(evt) {
    pwaOverlay.style.display = 'block';
    $('#pwa-overlay .app').show();
    $('#pwa-overlay .push').hide();
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then((choice) => {
        if (choice.outcome === 'accepted') {
            $('.install-pwa').addClass('processing')
        } else {
            console.log('User dismissed the A2HS prompt', choice);
        }
        deferredInstallPrompt = null;
        pwaOverlay.style.display = 'none';
    });
    evt.srcElement.setAttribute('hidden', true);
}

function revokeInstallAndRemember() {
    $('.install-promotion').remove();
    let expires = (new Date()).getTime() + 45 * 24 * 60 * 60 * 1000;  // Remember choice for 45 days
    expires = new Date(expires);
    ikwen.CookieUtil.set('install_revoked', 'yes', expires, null, null)
}

window.addEventListener('appinstalled', logAppInstalled);

/**
 * Event handler for appinstalled event.
 *   Log the installation to analytics or save the event somehow.
 *
 * @param {Event} evt
 */
function logAppInstalled(evt) {
    $('.install-promotion').fadeOut();
    $.getJSON('/analytics', {action: 'log_pwa_install'})
}

function urlB64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

function initializePushUI() {
    $('body').on('click', '.push-subscribe-btn:not(.disabled)', subscribeUser);

    // Set the initial subscription value
    swRegistration.pushManager.getSubscription().then(function(subscription) {
        isSubscribed = !(subscription === null);
        let pushSubscription = localStorage.getItem('pushSubscription');
        if (subscription && (pushSubscription !== JSON.stringify(subscription))) updateSubscriptionOnServer(subscription);
        if (isSubscribed) {
            console.log('User IS subscribed.');
        } else {
            console.log('User is NOT subscribed.');
        }
        updateWidget();
    });
}

function updateWidget() {
    if (isSubscribed) {
        $('.push-subscribe').remove();
        $('.push-unsubscribe').show();
    } else {
        $('.push-subscribe').show();
        $('.push-unsubscribe').remove();
    }
}

function subscribeUser() {
    $('.push-subscribe-btn').addClass('disabled');
    $('#pwa-overlay .app').hide();
    $('#pwa-overlay .push').show();
    pwaOverlay.style.display = 'block';
    const applicationServerKey = urlB64ToUint8Array(applicationServerPublicKey);
    swRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey
    }).then(function(subscription) {
        console.log('User is subscribed.');
        updateSubscriptionOnServer(subscription);
        isSubscribed = true;
        updateWidget();
        pwaOverlay.style.display = 'none';
    }).catch(function(err) {
        console.log('Failed to subscribe the user: ', err);
        updateWidget();
        pwaOverlay.style.display = 'none';
    });
}

function unsubscribeUser() {
    // TODO: Implement unsubscription here
}

function updateSubscriptionOnServer(subscription) {
    $.ajax({
        url: '/update_push_subscription',
        method: 'POST',
        data: {value: JSON.stringify(subscription)},
        success: function(resp) {
            resp = JSON.parse(resp);
            if (resp.success) localStorage.setItem('pushSubscription', JSON.stringify(subscription));
        }
    });
}
