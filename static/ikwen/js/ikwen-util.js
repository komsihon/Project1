/*!
 * Name:        ikwen-util
 * Version:     1.6.2
 * Description: Utility javascript functions and creation of the namespace
 * Author:      Kom Sihon
 * Support:     http://d-krypt.com
 *
 * Depends:
 *      jquery.js http://jquery.org
 *
 * Date: Sat Nov 10 07:55:29 2012 -0500
 */
(function(w) {
    var c = function() {
        return new c.fn.init()
    };
    c.fn = c.prototype = {
        init: function(){return this}
    };
    /**
     * Populate a target FancyComboBox based on a JSON Array of input data
     * fetched from a URL
     * @param endPoint the URL of JSON Array of data
     * @param params additional GET parameters
     * @param targetSelector selector of target FancyComboBox
     * @param value to select after the combo is filled
     */
    c.populateBasedOn = function(endPoint, params, targetSelector, value) {
        var options = '<li class="entry" data-val=""">---------</li>';
        $(targetSelector).next('.spinner').show();
        $.getJSON(endPoint, params, function(data) {
        $(targetSelector).next('.spinner').hide();
            for (var i=0; i<data.length; i++) {
               options += '<li class="entry" data-val="' + data[i].id + '">' + data[i].title + '</li>';
            }
            $(targetSelector).data('val', '').find('input:hidden').val('');
            $(targetSelector + ' .entries').html(options);
            $(targetSelector + ' input:text').val('---------');
            if (value) {
                var text = $(targetSelector + ' .entry[data-val=' + value + ']').text();
                $(targetSelector).data('val', value).find('input:hidden').val(value);
                $(targetSelector + ' input:text').val(text);
            }
        })
    };
    Number.prototype.formatMoney = function(decPlaces, thouSeparator, decSeparator) {
        var n = this,
        decPlaces = isNaN(decPlaces = Math.abs(decPlaces)) ? 0 : decPlaces,
        decSeparator = decSeparator == undefined ? "." : decSeparator, thouSeparator = thouSeparator == undefined ? "," : thouSeparator,
        sign = n < 0 ? "-" : "",
        i = parseInt(n = Math.abs(+n || 0).toFixed(decPlaces)) + "",
        j = (j = i.length) > 3 ? j % 3 : 0;
        return sign + (j ? i.substr(0, j) + thouSeparator : "") + i.substr(j).replace(/(\d{3})(?=\d)/g, "$1" + thouSeparator) + (decPlaces ? decSeparator + Math.abs(n - i).toFixed(decPlaces).slice(2) : "");
    };
    Number.prototype.pad = function(size) {
        var s = String(this);
        while (s.length < (size || 2)) {s = "0" + s;}
        return s;
    };
    String.prototype.isValidEmail = function() {
        return /^[a-zA-Z0-9_]+(\.*\-*[a-zA-Z0-9_]+)*\@[a-zA-Z0-9_]+(\-*[a-zA-Z0-9_])*(\.[a-zA-Z0-9_]+)*\.[a-zA-Z]{2,4}$/.test(this)
    };
    if(typeof(String.prototype.trim) === "undefined") {
        String.prototype.trim = function() {
            return String(this).replace(/^\s+|\s+$/g, '');
        };
    }
    c.getRandomInt = function(min, max) {
        return Math.floor(Math.random() * (max - min + 1) + min);
    };
    c.CookieUtil = {
        get: function (name) {
            var cookieName = encodeURIComponent(name) + '=',
            cookieStart = document.cookie.indexOf(cookieName),
            cookieValue = null;
            if (cookieStart > -1) {
                var cookieEnd = document.cookie.indexOf(';', cookieStart);
                if (cookieEnd == -1){
                    cookieEnd = document.cookie.length;
                }
                cookieValue = decodeURIComponent(document.cookie.substring(cookieStart + cookieName.length, cookieEnd));
            }
            return cookieValue;
        },
        set: function (name, value, expires, path, domain, secure) {
            var cookieText = encodeURIComponent(name) + '=' +
            encodeURIComponent(value);
            if (expires instanceof Date) {
                cookieText += '; expires=' + expires.toGMTString();
            }
            if (path) {
                cookieText += '; path=' + path;
            }
            if (domain) {
                cookieText += '; domain=' + domain;
            }
            if (secure) {
                cookieText += '; secure';
            }
            document.cookie = cookieText;
        },
        unset: function (name, path, domain, secure){
            this.set(name, '', new Date(0), path, domain, secure);
        }
    };

    c.showFloatingNotice = function(message, className, duration) {
        $('div#top-notice-ctnr span').removeClass('success failure').html(message).addClass(className);
        if (!duration) duration = 6;
        $('#top-notice-ctnr').fadeIn().delay(duration * 1000).fadeOut();
    };

    /**
     * Pops up a Modal to show a notice. Interesting for handling AJAX responses
     *
     * @param typeOrImageURL : String containing either 'Success', 'Error' or URL of an image. That is used to
     *                         modify the look of the modal
     * @param title : title of the modal
     * @param message : message to show in the modal
     * @param url : url of the OK button of the dialog
     * @param OKText : text on the OK button. Defaults to "OK"
     * @param cancelText : text on the Cancel button. Defaults to "Cancel". Set it to null to remove the Cancel button
     */
    c.showNoticeDialog = function(typeOrImageURL, title, message, url, OKText, cancelText) {
        $('#modal-generic-notice .title').html(title);
        $('#modal-generic-notice .message').html(message);
        if (url) $('#modal-generic-notice .btn-ok').prop('href', url);
        else $('#modal-generic-notice .btn-ok').prop('href', 'javascript:;');
        if (OKText) $('#modal-generic-notice .btn-ok').text(OKText);
        else $('#modal-generic-notice .btn-ok').text("OK");
        if (cancelText) $('#modal-generic-notice .btn-cancel').show().text(cancelText);
        else $('#modal-generic-notice .btn-cancel').show().text("Cancel");
        if (cancelText === null) $('#modal-generic-notice .btn-cancel').hide();
        $('#modal-generic-notice .illustration').hide();
        if (typeOrImageURL.toLowerCase() === 'success') $('#modal-generic-notice .success').show();
        else if (typeOrImageURL.toLowerCase() === 'error')$('#modal-generic-notice .error').show();
        else $('#modal-generic-notice .cover').css('background-image', `url(${typeOrImageURL})`).show();
        $('#modal-generic-notice').modal({backdrop: 'static', keyboard: false});
    };

    let call = [];
    c.setupSearch = function(inputSelector, resultPanelSelector, descriptors, beforeSearch, afterResults) {
        $('body').on('keyup', inputSelector, function() {
            let q = $(inputSelector).val(),
                min = $(resultPanelSelector).data('min-search-chars');
            if (min) {
                if (q.length < parseInt(min)) {
                    $(resultPanelSelector).hide();
                    call = [];
                    return;
                }
            }
            if (beforeSearch) {
                if (beforeSearch() === false) return;
            }
            $(resultPanelSelector).find('.empty').hide();
            if (call.length === 0) $(resultPanelSelector).find('.spinner').show();
            $(resultPanelSelector).show();
            for (let i=0; i<descriptors.length; i++) {
                let descriptor = descriptors[i],
                    url = descriptor.endpoint,
                    params = {q: q, start: 0, length: 10, format: 'json'},
                    selector = descriptor.resultTplSelector,
                    maxChars = descriptor.maxChars;  // The maximum number of chars to take into consideration
                if (maxChars) {
                    try {
                        params.max_chars = maxChars();
                    } catch (e) {
                        params.max_chars = maxChars
                    }
                }
                call.push(q);
                grabResults(url, params, resultPanelSelector, selector, call.length, afterResults, descriptor.jsonp);
                // TODO: Manage multiple descriptors and sectioned results
            }
        });
    };

    c.setupHTMLResultsSearch = function(inputSelector, resultPanelSelector, descriptors) {
        $(inputSelector).keyup(function() {
            let q = $(inputSelector).val(),
                min = $(inputSelector).data('min-search-chars');
            if (min) {
                if (q.length > 0 && q.length < parseInt(min)) {
                    call = [];
                    return;
                }
            }
            // if (call.length == 0) $(resultPanelSelector).find('.spinner').show();
            let length = descriptors.length;
            for (let i=0; i<length; i++) {
                let descriptor = descriptors[i],
                    url = descriptor.endpoint,
                    query = 'q=' + q + '&format=html_results';
                call.push(q);
                $.ajax({
                    url: url
                });
                $(resultPanelSelector).load(url, query, function() {
                    $(resultPanelSelector).find('.spinner').fadeOut();
                });
            }
        });
    };

    c.setupFilter = function(resultPanelSelector, descriptor, beforeSearch, afterResults) {
        $('#admin-nav').on('click', '.choices li', function () {
            $(this).siblings().removeClass('active');
            $(this).addClass('active');
            if (beforeSearch) beforeSearch();
            $(resultPanelSelector).find('.empty').hide();
            $(resultPanelSelector).show().find('.spinner').show();
            let url = descriptor.endpoint,
                params = {start: 0, length: 100, format: 'json'},
                selector = descriptor.resultTplSelector;
            $('div#admin-nav .filter li.active').each(function () {
                let paramName = $(this).parent().data('param');
                params[paramName] = $(this).data('value');
            });
            grabResults(url, params, resultPanelSelector, selector, call.length, afterResults);
        });
    };

    c.setupHTMLResultsFilter = function(descriptor, beforeSearch, afterResults) {
        $('#admin-content').on('change', '#admin-tools .filter select', function() {
            let resultPanelSelector = descriptor.resultPanelSelector;
            if (beforeSearch) beforeSearch();
            $(resultPanelSelector).find('.empty').hide();
            $(resultPanelSelector).show().find('.spinner').fadeIn();
            var url = window.location.pathname,
                params = {start: 0, length: 100, format: 'html_results'};
            $('div#admin-tools .filter select').each(function() {
                let paramName = $(this).prop('name');
                if (paramName) params[paramName] = $(this).val();
            });
            $('div#admin-tools .filter input').each(function() {
                let paramName = $(this).prop('name');
                if (paramName) params[paramName] = $(this).val();
            });
            params['q'] = $('#context-search').val();
            let query = window.location.search,
                paramString = '';
            for (let key in params) {
                paramString += '&' + key + '=' + params[key]
            }
            if (query && query !== '?') query += paramString;
            else query = paramString.substr(1);
            $(resultPanelSelector).load(url, query, function() {
                $(resultPanelSelector).find('.spinner').fadeOut();
                for (let key in params) {
                    $('#' + key).val(params[key])
                }
                if (afterResults) afterResults();
            });
        });
    };

    function grabResults(url, params, resultPanelSelector, resultSelector, callSeqNumber, afterResults, jsonp) {
        if (jsonp) url.indexOf('?') === -1 ? url += '?callback=?' : url += '&callback=?';
        $.getJSON(url, params, function(data) {
            if (call[call.length - 1] !== params['q']) return;  // Show results only for the last value of q
            $(resultPanelSelector).find('.spinner').hide();
            if (data.error) {
                c.showFloatingNotice(data.error);
                return;
            }
            if (data.length === 0) $(resultPanelSelector).find('.empty').show();
            $(resultSelector + ':not(.tpl)').remove();
            let objectList = jsonp ? data.object_list : data;
            for (let i=0; i<objectList.length; i++) {
                let $tpl = $(resultSelector + '.tpl').clone().removeClass('tpl');
                $tpl = c.genericTemplateFunc($tpl, objectList[i]);
                $tpl.insertBefore(resultSelector + '.tpl').show();
            }
            if (afterResults) afterResults(data);
        });
    }

    c.genericTemplateFunc = function($tpl, object, searchTerm) {
        for (var field in object) {
            var value = object[field],
                content = value,
                $fieldElt = $tpl.find('.' + field);
            if (searchTerm) content = value.replace(searchTerm, '<strong>' + searchTerm + '</strong>');
            if (typeof value == 'number') content = content.formatMoney();
            if ($fieldElt.hasClass('bg-img')) $fieldElt.css('background-image', 'url(' + value + ')');
            else if ($fieldElt.prop('tagName') == 'IMG') $fieldElt.attr('src', value);
            else {
                if ($fieldElt.hasClass('hide') && content) $fieldElt.removeClass('hide');
                if ($fieldElt.find('.value').length > 0) {
                    if (!content && $fieldElt.hasClass('n-a')) $fieldElt.find('.value').text('N/A');
                    else if (content) {
                        if ($fieldElt.hasClass('in-brackets')) $fieldElt.find('.value').html('(' + content + ')');
                        $fieldElt.find('.value').html(content);
                    }
                } else {
                    if (!content && $fieldElt.hasClass('n-a')) $fieldElt.text('N/A');
                    else if (content) {
                        if ($fieldElt.hasClass('in-brackets')) $fieldElt.html('(' + content + ')');
                        else $fieldElt.html(content);
                    }
                }
            }
            if (field == 'url') {
                if (ikwen.URL_KEY && ikwen.URL_RAND) {
                    if (value.indexOf('?') == -1 ) value += '?key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                    else value += '&key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                }
                $tpl.find('.target_url').attr('href', value);
            }
            if (field == 'id') $tpl.attr('id', value);
            if (typeof value == 'string' || typeof value == 'number') $tpl.data(field, value);

            /* Some common boolean fields */
            if (field == 'status') $tpl.addClass(value)
        }
        return $tpl
    };

    let $epl = $('.edge-panel-left'),
        $eso = $('.edge-swipe-overlay'),
        isMenuSwipe = false;
    $('body').on('click', '.nav-tabs .tab', function() {
        $('.nav-tabs .tab').removeClass('active');
        $(this).addClass('active');
        if ($(this).hasClass('swiper-slide') && contentTabPaneSwiper) {
            let i = $(this).index();
            contentTabPaneSwiper.slideTo(i, 300, false)
        }
    }).on('click', '.menu-button', function() {
        showEdgePanelLeft();
    }).on('click', '.edge-swipe-overlay', function(e) {
        let elt = e.target.className;
        if (elt.indexOf('edge-swipe-overlay') >= 0 || elt.indexOf('close') >= 0) {
            history.back();  // Causes the processHash() function to run
        }
    });
    $(window).on('hashchange', processHash);
    function processHash() {
        if (location.hash.length < 1) {
            hideEdgePanelLeft();
            if ($(window).width() < 768 || $('.edge-panel-right').hasClass('always-docked')) {
                hideEdgePanelRight();
            }
        }
    }
    try {
        if ($(window).width() > 768) throw "Pan events not suited here." ;
        $('body').hammer().bind("panstart", function(ev) {
            isMenuSwipe = ev.gesture.center.x > 0 && ev.gesture.center.x <= 40 && !$eso.is(':visible');
        }).bind("pan", function(ev) {
            if (!isMenuSwipe) return;
            showEdgePanelLeft()
        });
        $eso.hammer().bind("pan", function(ev) {
            var deltaX = ev.gesture.deltaX;
            var deltaY = Math.abs(ev.gesture.deltaY);
            if (deltaY >= 10) return;
            if ($epl.is(':visible')) {
                if (deltaX > 0) return;
                $epl.css({marginLeft: deltaX + 'px'})
            } else {
                if (deltaX < 0) return;
                $('.edge-panel-right').css({marginRight: '-' + deltaX + 'px'})
            }
        }).bind("panend", function(ev) {
            if ($epl.is(':visible')) {
                var eplWidth = $epl.width(),
                    ml = parseInt($epl.css('margin-left'));
                if (Math.abs(ml) > (eplWidth/10)) {
                    $epl.animate({marginLeft: '-' + eplWidth + 'px'}, 'fast', 'linear', function() {
                        $(this).hide();
                    });
                    history.back();  // Causes the processHash() function to run
                } else $epl.animate({marginLeft: 0}, 'fast');
            } else {
                var eprWidth = $('.edge-panel-right').width(),
                    mr = parseInt($('.edge-panel-right').css('margin-right'));
                if (Math.abs(mr) > (eprWidth/10)) {
                    $('.edge-panel-right').animate({marginRight: '-' + eprWidth + 'px'}, 'fast', 'linear', function() {
                        $(this).hide();
                    });
                    history.back();  // Causes the processHash() function to run
                } else $('.edge-panel-right').animate({marginRight: 0}, 'fast');
            }
        });
        $('.edge-panel-left, .edge-panel-right').hammer().bind("pan", function(ev) {
            ev.stopPropagation()
        }).bind("panend", function(ev) {
            ev.stopPropagation()
        });
    } catch (e) {}

    function showEdgePanelLeft() {
        if ($epl.length === 0) return;
        $eso.fadeIn('fast');
        $epl.show().animate({marginLeft: 0}, 'fast');
        location.hash = 'edge-panel-disclosed';
    }

    function hideEdgePanelLeft() {
        var width = $epl.width();
        $epl.animate({marginLeft: '-' + width + 'px'}, 'fast', 'linear', function() {
            $(this).hide();
        });
        $eso.fadeOut('fast');
    }

    function hideEdgePanelRight() {
        var width = $('.edge-panel-right').width();
        $('.edge-panel-right').animate({marginRight: '-' + width + 'px'}, 'fast', 'linear', function() {
            $(this).hide();
        });
        $eso.fadeOut('fast');
    }

    c.debouncer = function(func, timeout) { // Trick to capture window resize ended event
       var timeoutID , timeout = timeout || 200;
       return function () {
          var scope = this , args = arguments;
          clearTimeout( timeoutID );
          timeoutID = setTimeout( function () {
              func.apply( scope , Array.prototype.slice.call( args ) );
          } , timeout );
       }
    };

    c.swipeInRightPanel = function() {
        $('.edge-swipe-overlay').fadeIn('fast');
        $('.edge-panel-right').show().addClass('has-shade').appendTo('.edge-swipe-overlay').animate({marginRight: 0}, 'fast');
        location.hash = 'edge-panel-disclosed';
    };

    let contentTabListSwiper, contentTabPaneSwiper, windowWidth = $(window).width();

    function initContentTabListSwiper() {
        if ($('.content-tab-list').length === 0 || contentTabListSwiper) return;

        $('.content-tab-list .nav-tabs').addClass('swiper-wrapper');
        $('.content-tab-list .tab').addClass('swiper-slide');
        contentTabListSwiper = new Swiper('.content-tab-list .swiper-container', {
            slidesPerView: 'auto',
            nextButton: '.swiper-button-next',
            prevButton: '.swiper-button-prev',
            breakpoints: {
                767: {
                    slidesPerView: 5
                },
                479: {
                    slidesPerView: 4
                },
                369: {
                    slidesPerView: 3
                }
             }
        });
        if ($(window).width() < 768) {
            $('.content-tab-list').addClass('bottom-shade');
            if ($('.tab-content .swiper-wrapper').length === 0) $('<div class="swiper-wrapper"></div>').prependTo('.tab-content');
            $('.tab-pane').addClass('swiper-slide').appendTo('.tab-content .swiper-wrapper');
            $('.tab-content').addClass('swiper-container');
            contentTabPaneSwiper = new Swiper('.tab-content.swiper-container', {
                slidesPerView: 1,
                spaceBetween: 15,
                onSlideChangeEnd: function (swiper) {
                    var i = swiper.activeIndex + 1;
                    $('.nav-tabs .tab:nth-child(' + i + ')').click();
                    contentTabListSwiper.slideTo(swiper.activeIndex)
                }
            });
            let i = $('.nav-tabs .tab.active').index();
            contentTabPaneSwiper.slideTo(i)
        } else {
            let totalTabWidths = 0;
            $('.content-tab-list .tab').each(function() {
                totalTabWidths += $(this).width();
            });
            if (totalTabWidths > $('.content-tab-list .nav-tabs').width()) {
                $('.swiper-button-prev, .swiper-button-next').removeClass('hidden')
            }
        }
    }

    c.reloadTabView = function() {
        let winWidth = $(window).width();
        if (contentTabListSwiper) {
            contentTabListSwiper.destroy();
            contentTabListSwiper = null;
        }
        if (contentTabPaneSwiper) {
            contentTabPaneSwiper.destroy();
            contentTabPaneSwiper = null;
        }
        initContentTabListSwiper();
        if (winWidth >= 768) {
            $('.content-tab-list').removeClass('bottom-shade');
            $('.tab-pane').removeClass('swiper-slide').appendTo('.tab-content');
            $('.tab-content .swiper-wrapper').remove();
            $('.tab-content').addClass('swiper-container');
        }
    };

    initContentTabListSwiper();

    $( window ).resize(c.debouncer(function (e) {
        var newWindowWith = $(window).width();
        if (newWindowWith >= 992) $epl.show().css('margin-left', 0);
        if ((windowWidth < 768 && newWindowWith > 768) || (windowWidth > 768 && newWindowWith < 768))
            c.reloadTabView();
    }));

    w.ikwen = c; /*Creating the namespace ikwen for all this*/
})(window);